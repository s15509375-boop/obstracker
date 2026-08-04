#!/usr/bin/env python3
from __future__ import annotations
import csv, math, re, sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

APP_DIR=Path(__file__).resolve().parent
DATA_DIR=APP_DIR/'smart_slot_data'; DB_PATH=DATA_DIR/'smart_slot_manager.db'; EXPORT_DIR=DATA_DIR/'exports'
LEVELS=['A','B','C','D']; LEVEL_ORDER={x:i for i,x in enumerate(LEVELS)}
STACK_MAX={'pallet_box':4,'sleeve':3,'wood_pallet':1,'rack':1,'other':1}
ALIASES={'gpu':['gpu','graphics','nvidia','t2','t3','baseboard'],'motherboard':['motherboard','mobo','mainboard'],'power_supply':['psu','power supply'],'bracket':['bracket'],'cable':['cable','dongle','fiber'],'ram':['ram','dimm','memory'],'foam':['foam'],'cardboard':['cardboard','cb'],'metal':['metal','copper','aluminum','heat sink','heatsink'],'mixed':['mixed']}

def now(): return datetime.now().isoformat(timespec='seconds')
def clean(v,n=120): return re.sub(r'\s+',' ',re.sub(r'[\x00-\x1f\x7f]',' ',v)).strip()[:n]
def pause(): input('\nPress Enter to continue...')
def clear(): print('\033[2J\033[H',end='')
def ask_int(p,lo=0,hi=999999,default=None):
    while True:
        r=input(p).strip()
        if not r and default is not None:return default
        try:
            v=int(r)
            if lo<=v<=hi:return v
        except: pass
        print(f'Enter a whole number from {lo} to {hi}.')
def yn(p): return input(p+' [y/N]: ').strip().lower() in {'y','yes'}
def norm_material(t):
    h=t.lower()
    for k,vals in ALIASES.items():
        if any(v in h for v in vals): return k
    return h or 'unknown'

def safe_csv(v):
    s=str(v)
    return "'"+s if s.startswith(('=','+','-','@')) else s

@dataclass
class Location:
    id:int; area:str; zone:str; column_no:int; level:str; max_weight:Optional[int]; allowed_types:str; purpose:str; distance_rank:int; active:int
    @property
    def code(self): return f'{self.area}-{self.zone}{self.column_no}{self.level}'
@dataclass
class Item:
    id:int; build_id:str; description:str; material:str; container_type:str; weight:int; priority:int; work_area:str; due_text:str; status:str; location_id:Optional[int]; created_at:str; updated_at:str

class DB:
    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True); EXPORT_DIR.mkdir(exist_ok=True)
        self.c=sqlite3.connect(DB_PATH); self.c.row_factory=sqlite3.Row
        self.c.execute('PRAGMA foreign_keys=ON'); self.c.execute('PRAGMA journal_mode=WAL'); self.c.execute('PRAGMA synchronous=FULL')
        self.c.executescript('''
        CREATE TABLE IF NOT EXISTS locations(id INTEGER PRIMARY KEY,area TEXT NOT NULL,zone TEXT NOT NULL,column_no INTEGER NOT NULL,level TEXT NOT NULL CHECK(level IN ('A','B','C','D')),max_weight INTEGER,allowed_types TEXT NOT NULL DEFAULT '*',purpose TEXT NOT NULL DEFAULT 'general',distance_rank INTEGER NOT NULL DEFAULT 50,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,UNIQUE(area,zone,column_no,level));
        CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY,build_id TEXT NOT NULL UNIQUE COLLATE NOCASE,description TEXT NOT NULL DEFAULT '',material TEXT NOT NULL DEFAULT 'unknown',container_type TEXT NOT NULL,weight INTEGER NOT NULL CHECK(weight>=0),priority INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 5),work_area TEXT NOT NULL DEFAULT '',due_text TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'stored',location_id INTEGER,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,FOREIGN KEY(location_id) REFERENCES locations(id));
        CREATE TABLE IF NOT EXISTS movements(id INTEGER PRIMARY KEY,item_id INTEGER NOT NULL,from_location_id INTEGER,to_location_id INTEGER,reason TEXT NOT NULL,moved_at TEXT NOT NULL,FOREIGN KEY(item_id) REFERENCES items(id));
        CREATE INDEX IF NOT EXISTS idx_material ON items(material); CREATE INDEX IF NOT EXISTS idx_loc ON items(location_id);
        '''); self.c.commit()
    def close(self): self.c.close()
    def add_location(self,*a): self.c.execute('INSERT OR IGNORE INTO locations(area,zone,column_no,level,max_weight,allowed_types,purpose,distance_rank,active,created_at) VALUES(?,?,?,?,?,?,?,?,1,?)',(*a,now())); self.c.commit()
    def locations(self): return [Location(**dict(r)) for r in self.c.execute("SELECT * FROM locations WHERE active=1 ORDER BY area,zone,column_no,CASE level WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 4 END")]
    def location(self,i):
        r=self.c.execute('SELECT * FROM locations WHERE id=?',(i,)).fetchone(); return Location(**dict(r)) if r else None
    def by_code(self,code):
        t=re.sub('[^A-Z0-9]','',code.upper())
        for l in self.locations():
            if re.sub('[^A-Z0-9]','',l.code.upper())==t:return l
    def occupied(self): return {r[0] for r in self.c.execute("SELECT location_id FROM items WHERE location_id IS NOT NULL AND status!='removed'")}
    def add_item(self,b,d,m,t,w,p,a,due):
        cur=self.c.execute("INSERT INTO items(build_id,description,material,container_type,weight,priority,work_area,due_text,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'unassigned',?,?)",(b,d,m,t,w,p,a,due,now(),now())); self.c.commit(); return cur.lastrowid
    def item(self,i):
        r=self.c.execute('SELECT * FROM items WHERE id=?',(i,)).fetchone(); return Item(**dict(r)) if r else None
    def find(self,b):
        r=self.c.execute('SELECT * FROM items WHERE build_id=? COLLATE NOCASE',(b,)).fetchone(); return Item(**dict(r)) if r else None
    def items(self): return [Item(**dict(r)) for r in self.c.execute("SELECT * FROM items WHERE status!='removed' ORDER BY priority DESC,created_at")]
    def assign(self,item_id,loc_id,reason):
        it=self.item(item_id)
        if loc_id is not None:
            r=self.c.execute("SELECT build_id FROM items WHERE location_id=? AND status!='removed' AND id!=?",(loc_id,item_id)).fetchone()
            if r: raise ValueError(f'Location occupied by {r[0]}')
        self.c.execute("UPDATE items SET location_id=?,status=?,updated_at=? WHERE id=?",(loc_id,'stored' if loc_id else 'unassigned',now(),item_id))
        self.c.execute('INSERT INTO movements(item_id,from_location_id,to_location_id,reason,moved_at) VALUES(?,?,?,?,?)',(item_id,it.location_id,loc_id,reason,now())); self.c.commit()
    def remove(self,item_id,reason):
        it=self.item(item_id); self.c.execute("UPDATE items SET status='removed',location_id=NULL,updated_at=? WHERE id=?",(now(),item_id)); self.c.execute('INSERT INTO movements(item_id,from_location_id,to_location_id,reason,moved_at) VALUES(?,?,NULL,?,?)',(item_id,it.location_id,reason,now())); self.c.commit()

class Optimizer:
    def __init__(self,db): self.db=db
    def below(self,l): return [x for x in self.db.locations() if x.area==l.area and x.zone==l.zone and x.column_no==l.column_no and LEVEL_ORDER[x.level]<LEVEL_ORDER[l.level]]
    def above(self,l): return [x for x in self.db.locations() if x.area==l.area and x.zone==l.zone and x.column_no==l.column_no and LEVEL_ORDER[x.level]>LEVEL_ORDER[l.level]]
    def valid(self,it,l,occupied):
        if l.id in occupied:return False
        if l.allowed_types not in ('','*') and it.container_type not in {x.strip() for x in l.allowed_types.split(',')}:return False
        if l.max_weight is not None and it.weight>l.max_weight:return False
        if LEVEL_ORDER[l.level]+1>STACK_MAX.get(it.container_type,1):return False
        if any(x.id not in occupied for x in self.below(l)):return False
        rows=self.db.c.execute("SELECT i.container_type FROM items i JOIN locations l ON i.location_id=l.id WHERE l.area=? AND l.zone=? AND l.column_no=? AND i.status!='removed'",(l.area,l.zone,l.column_no)).fetchall()
        if any(r[0]!=it.container_type for r in rows):return False
        return True
    def score(self,it,l):
        s=0; why=[]; blob=f'{l.area} {l.zone} {l.purpose}'.lower(); work=it.work_area.lower()
        if work and work in blob:s+=120;why.append('matches work area')
        elif work:s-=35
        if it.material!='unknown' and it.material in l.purpose.lower():s+=55;why.append('matches purpose')
        s+=max(0,60-l.distance_rank)
        idx=LEVEL_ORDER[l.level]; access=idx/3
        if it.priority>=4:s+=100*access;why.append('high priority accessible')
        elif it.priority==3:s+=35*access
        else:s+=50*(1-access);why.append('low priority deeper')
        same=self.db.c.execute("SELECT COUNT(*) FROM items i JOIN locations x ON i.location_id=x.id WHERE x.area=? AND x.zone=? AND i.material=? AND ABS(x.column_no-?)<=2 AND i.status!='removed'",(l.area,l.zone,it.material,l.column_no)).fetchone()[0]
        if same:s+=min(40,same*10);why.append('groups similar material')
        stack=self.db.c.execute("SELECT COUNT(*) FROM items i JOIN locations x ON i.location_id=x.id WHERE x.area=? AND x.zone=? AND x.column_no=? AND i.status!='removed'",(l.area,l.zone,l.column_no)).fetchone()[0]
        if stack:s+=25;why.append('fills compatible stack')
        if it.weight>=1000:s+=(3-idx)*22;why.append('heavy item lower')
        return s,why
    def recommend(self,it,limit=8):
        occ=self.db.occupied(); out=[]
        for l in self.db.locations():
            if self.valid(it,l,occ):
                s,w=self.score(it,l); out.append((l,s,w))
        return sorted(out,key=lambda x:x[1],reverse=True)[:limit]
    def retrieval(self,q):
        q=q.lower(); nm=norm_material(q); occ=self.db.occupied(); out=[]
        for it in self.db.items():
            blob=f'{it.build_id} {it.description} {it.material} {it.container_type}'.lower()
            if q not in blob and nm!=it.material:continue
            l=self.db.location(it.location_id) if it.location_id else None
            blockers=sum(1 for x in self.above(l) if x.id in occ) if l else 99
            out.append((it,l,blockers,blockers*2+1))
        return sorted(out,key=lambda x:(x[2],-x[0].priority))
    def reorganize(self):
        out=[]
        for it in self.db.items():
            if not it.location_id:continue
            cur=self.db.location(it.location_id); cs,_=self.score(it,cur); rec=self.recommend(it,1)
            if rec and rec[0][1]-cs>=45: out.append((it,cur,rec[0][0],rec[0][1]-cs,rec[0][2]))
        return sorted(out,key=lambda x:x[3],reverse=True)[:20]

def setup(db):
    clear(); print('CONFIGURE STORAGE LOCATIONS\n')
    area=clean(input('Area (BUFFER/MLAB2): '),30).upper(); zone=clean(input('Zone (Z1/A/etc.): '),20).upper(); start=ask_int('Starting spot: ',1,9999); end=ask_int('Ending spot: ',start,9999); levels=ask_int('Levels 1-4: ',1,4); purpose=clean(input('Purpose: ') or 'general',50).lower(); allowed=clean(input('Allowed types comma-separated or *: ') or '*',100).lower(); dist=ask_int('Distance rank 1-100 [50]: ',1,100,50); mw=input('Max weight per level, blank none: ').strip(); mw=int(mw) if mw.isdigit() else None
    for col in range(start,end+1):
        for lev in LEVELS[:levels]:db.add_location(area,zone,col,lev,mw,allowed,purpose,dist)
    print('Configured.');pause()
def show_map(db):
    clear(); print('STORAGE MAP\n'); by={}; items={i.location_id:i for i in db.items() if i.location_id}
    for l in db.locations():by.setdefault((l.area,l.zone,l.column_no),[]).append(l)
    for k,locs in sorted(by.items()):
        area,zone,col=k; parts=[]
        for l in sorted(locs,key=lambda x:LEVEL_ORDER[x.level]):parts.append(f"{l.level}:{items[l.id].build_id[:12] if l.id in items else 'EMPTY'}")
        print(f'{area}/{zone}{col}: '+' | '.join(parts))
    pause()
def intake(db,opt):
    clear(); print('FAST INTAKE\n'); b=clean(input('Build ID: '),80)
    if not b:return
    if db.find(b):print('Build already exists.');pause();return
    d=clean(input('Description/contents: '),160); m=norm_material(clean(input('Primary material/category: '),80)); print('1 pallet_box  2 sleeve  3 wood_pallet  4 rack  5 other'); t={'1':'pallet_box','2':'sleeve','3':'wood_pallet','4':'rack','5':'other'}.get(input('Type: ').strip(),'other'); w=ask_int('Weight whole lb [0 unknown]: ',0,100000); p=ask_int('Priority 1-5: ',1,5); a=clean(input('Preferred work area: '),30).upper(); due=clean(input('Forecast/note: '),80)
    try:i=db.item(db.add_item(b,d,m,t,w,p,a,due))
    except sqlite3.IntegrityError:print('Duplicate build.');pause();return
    rec=opt.recommend(i)
    if not rec:print('No compatible location; left unassigned.');pause();return
    for n,(l,s,r) in enumerate(rec,1):print(f'{n}. {l.code:<18} {s:6.1f} | {"; ".join(r[:3])}')
    x=input('Choose number/location or Enter unassigned: ').strip()
    if not x:return
    l=rec[int(x)-1][0] if x.isdigit() and 1<=int(x)<=len(rec) else db.by_code(x)
    if l:
        try:db.assign(i.id,l.id,'Initial intake');print('Assigned to',l.code)
        except ValueError as e:print(e)
    pause()
def baseline(db):
    clear();print('BASELINE CURRENT FLOOR (type DONE to finish)\n')
    while True:
        b=clean(input('Build ID: '),80)
        if b.upper()=='DONE':break
        it=db.find(b)
        if not it:
            d=clean(input('Description: '),160);m=norm_material(clean(input('Material: '),80));t=clean(input('Type pallet_box/sleeve/wood_pallet/rack/other: '),30).lower();t=t if t in STACK_MAX else 'other';w=ask_int('Weight [0 unknown]: ',0,100000);p=ask_int('Priority 1-5 [2]: ',1,5,2);a=clean(input('Preferred work area: '),30).upper();due=clean(input('Forecast: '),80);it=db.item(db.add_item(b,d,m,t,w,p,a,due))
        l=db.by_code(clean(input('Current location: '),40))
        if not l:print('Location not found.');continue
        try:db.assign(it.id,l.id,'Baseline floor scan');print('Saved.\n')
        except ValueError as e:print(e)
def search(db,opt):
    clear();q=clean(input('Search build/material: '),100);r=opt.retrieval(q);print('\nEASIEST RETRIEVAL FIRST\n')
    for n,(i,l,b,moves) in enumerate(r,1):print(f'{n}. {i.build_id:<24} {(l.code if l else "UNASSIGNED"):<18} blockers:{b} moves:{moves} priority:{i.priority}')
    if not r:print('No matches.')
    pause()
def capacity(db):
    clear();locs=db.locations();occ=db.occupied();total=len(locs);used=len(occ);print('CAPACITY DASHBOARD\n')
    print(f'{used}/{total} occupied | {total-used} free | {(used/total*100 if total else 0):.1f}% full')
    groups={}
    for l in locs:groups.setdefault((l.area,l.zone),[]).append(l)
    for k,v in sorted(groups.items()):u=sum(1 for l in v if l.id in occ);print(f'{k[0]}/{k[1]}: {u}/{len(v)} ({u/len(v)*100:.1f}%)')
    reserve=math.ceil(total*.10);print(f'\nSuggested additional single-slot releases: {max(0,total-used-reserve)}');pause()
def reorganize(db,opt):
    clear();print('REORGANIZATION SUGGESTIONS\n');r=opt.reorganize()
    for n,(i,c,t,imp,why) in enumerate(r,1):print(f'{n}. {i.build_id}: {c.code} -> {t.code} | +{imp:.1f} | {"; ".join(why[:3])}')
    if not r:print('No high-confidence moves found.')
    print('\nAdvisory only; verify the floor before moving anything.');pause()
def move(db,opt):
    clear();b=clean(input('Build ID: '),80);i=db.find(b)
    if not i:print('Not found.');pause();return
    rec=opt.recommend(i)
    for n,(l,s,r) in enumerate(rec,1):print(f'{n}. {l.code} {s:.1f} {"; ".join(r[:2])}')
    x=input('Choose/location: ').strip();l=rec[int(x)-1][0] if x.isdigit() and 1<=int(x)<=len(rec) else db.by_code(x)
    if l:
        try:db.assign(i.id,l.id,'Manual move');print('Moved.')
        except ValueError as e:print(e)
    pause()
def update_priority(db):
    clear();i=db.find(clean(input('Build ID: '),80))
    if not i:print('Not found.');pause();return
    p=ask_int('Priority 1-5: ',1,5);due=clean(input(f'Forecast [{i.due_text}]: '),80) or i.due_text;a=clean(input(f'Work area [{i.work_area}]: '),30).upper() or i.work_area;db.c.execute('UPDATE items SET priority=?,due_text=?,work_area=?,updated_at=? WHERE id=?',(p,due,a,now(),i.id));db.c.commit();pause()
def remove(db):
    clear();i=db.find(clean(input('Build ID: '),80))
    if i and yn('Remove/ship and free location?'):db.remove(i.id,clean(input('Reason: '),80));print('Removed.')
    pause()
def export(db):
    EXPORT_DIR.mkdir(exist_ok=True);p=EXPORT_DIR/f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with p.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['build_id','description','material','container_type','weight','priority','work_area','due','status','location'])
        for i in db.items():
            l=db.location(i.location_id) if i.location_id else None;w.writerow([safe_csv(i.build_id),safe_csv(i.description),safe_csv(i.material),i.container_type,i.weight,i.priority,safe_csv(i.work_area),safe_csv(i.due_text),i.status,safe_csv(l.code if l else '')])
    print('Exported',p);pause()
def menu():
    db=DB();opt=Optimizer(db)
    try:
        while True:
            clear();print('='*72+'\nSMART SLOT MANAGER V1\n'+'='*72);print('1 Configure locations\n2 Baseline current floor\n3 Fast intake + suggestion\n4 View storage map\n5 Search/easiest retrieval\n6 Move build\n7 Capacity dashboard\n8 Reorganization suggestions\n9 Update priority/forecast\n10 Remove/ship build\n11 Export snapshot\n0 Exit')
            c=input('> ').strip();a={'1':lambda:setup(db),'2':lambda:baseline(db),'3':lambda:intake(db,opt),'4':lambda:show_map(db),'5':lambda:search(db,opt),'6':lambda:move(db,opt),'7':lambda:capacity(db),'8':lambda:reorganize(db,opt),'9':lambda:update_priority(db),'10':lambda:remove(db),'11':lambda:export(db)}
            if c=='0':break
            if c in a:a[c]()
            else:pause()
    finally:db.close()
if __name__=='__main__':
    try:menu()
    except KeyboardInterrupt:print('\nStopped safely.')

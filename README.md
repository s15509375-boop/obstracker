# Outbound Tracker V2

## Overview

Outbound Tracker V2 is an offline proof-of-concept application developed to streamline the outbound shipping workflow for palletized recycling and material shipments.

The primary objective of this project is to reduce repetitive manual data entry, provide a visual representation of truck loading, improve organization of RZRR loads throughout a shift, and generate consistent output for existing operational processes.

This application is **not intended to replace existing company systems**. Instead, it serves as a workflow aid and demonstrates how several manual processes can be consolidated into a single application.

---

# Features

### Rapid Data Entry

* Fast entry of bin name, seal, weight, container type, and material.
* Optimized for barcode scanners that function as keyboard input.
* Supports both scanned and manually entered seals.

### RZRR Management

* Create and manage multiple RZRRs.
* Track container information throughout the workflow.
* Optional dock assignment.
* Lock completed RZRRs after Security approval.

### Truck Load Visualization

* Automatic trailer layout generation.
* 24 floor position visualization.
* Mixed container support.
* Capacity validation.

Supported container types:

* Plastic Pallet Boxes
* Pallet Sleeves
* Wood Pallets

Rules enforced:

* Plastic pallet boxes may stack two high.
* Pallet sleeves may stack two high.
* Plastic pallet boxes and pallet sleeves cannot share the same stack.
* Wood pallets occupy one floor position and cannot be stacked.

### Dock Preparation

* Manual dock ordering.
* Generates Security verification order.
* Designed to match physical loading workflow.

### Issues / Mobility Output

Automatically generates formatted output for manual copy/paste into existing operational systems.

Example:

```text
1. BIN001 - SEAL001
2. BIN002 - SEAL002
3. BIN003 - SEAL003
```

---

# Current Workflow

Typical workflow:

1. Create a new RZRR.
2. Scan or enter each bin.
3. Scan or enter the seal.
4. Enter the weight.
5. Select the container type.
6. Enter an optional material description.
7. Assign the RZRR to an OBS aisle.
8. Move the RZRR to the dock.
9. Build the dock order.
10. Generate the Issues/Mobility list.
11. Security verifies the printed list.
12. Mark the RZRR as Security Approved.
13. Load the truck.

---

# Project Status

Current Version:

**V2 – Proof of Concept**

This version demonstrates the overall workflow and user interface while validating the operational concept.

Future versions may include additional workflow improvements based on real-world testing and user feedback.

---

# Security Considerations

This application was intentionally designed with a minimal attack surface and is intended as an **offline proof of concept**.

## Current Security Design

* Offline operation only
* No network communication
* No cloud services
* No telemetry
* No browser automation
* No automated interaction with external systems
* No administrator privileges required
* Standard Python library only
* No third-party dependencies
* JSON-based local storage
* Avoids unsafe serialization methods such as `pickle`
* Basic validation of required fields
* Duplicate detection for bins and seals within an RZRR
* CSV export protection against common spreadsheet formula injection
* Atomic file saving to reduce file corruption risk

## Current Limitations

This project is **not a production system**.

Future security improvements include:

* Stronger validation of saved data
* Integrity verification for approved records
* Audit logging
* Additional error handling
* Role-based permissions if multi-user support is ever implemented
* Expanded testing and validation

## Intended Use

This project is intended for:

* Demonstration
* Workflow evaluation
* Personal development
* Process improvement discussions

It is **not** intended to replace official company systems and should only be evaluated using non-production or appropriately authorized data unless approved through the organization's review process.

---

# Future Improvements

Potential future enhancements include:

* Persistent staging area tracking
* Multi-truck support
* Multiple RZRRs assigned to a single truck
* Improved dock visualization
* Better search functionality
* Enhanced trailer editing
* Faster barcode-driven workflow
* Additional reporting
* Improved validation
* Expanded testing
* Performance optimizations
* Optional configuration profiles
* Additional security hardening

---

# Requirements

* Python 3.10 or newer
* Windows, Linux, or macOS
* No external Python packages required

---

# Running the Application

```bash
python outbound_tracker_v2.py
```

---

# Disclaimer

This software was developed as an independent proof-of-concept project for learning, workflow analysis, and process improvement.

Any references to operational workflows are intended solely to demonstrate software design concepts. This application does not connect to, modify, or replace any existing operational systems and should only be used in accordance with applicable organizational policies and approval processes.

---

# Developer Note

This project was created to combine practical software engineering with secure software design principles. My background in cybersecurity influenced several architectural decisions, including minimizing the attack surface by avoiding unnecessary dependencies, network communication, automated interaction with external systems, and elevated privileges.

The long-term goal is to continue refining the application through testing, user feedback, and additional security hardening while maintaining a simple, transparent, and maintainable codebase.

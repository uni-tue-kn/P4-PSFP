# P4-PSFP: P4-Based Per-Stream Filtering and Policing for Time-Sensitive Networking

This repository contains the source code for a P4 based implementation of PSFP on the Intel Tofino(TM) ASIC.

## Installation & Start Instructions

### P4 Program

Compile P4-PSFP via `make compile`. This compiles the program and copies the resulting configs to the target directory.

Afterwards, start P4-PSFP via `make start`.

This requires a fully setup SDE with set `$SDE` and `$SDE_INSTALL` environment variables. Adapt the paths in the `Makefile` as needed.

Tested on:
- SDE 9.9.0
- SDE 9.13.0

### Controller

The controller is written python and can be started via `python3 Local-Controller/controller.py`.

### PSFP Configuration

The PSFP configuration file is located in `Local-Controller/configuration.json`. 
The following configuration options are there:
- Stream Identification
- Stream Filtering
- Stream Gates
- Stream Gate Control Lists
- Schedule to Port mapping
- Flow Meters

#### Stream Identification

Assigns a stream_handle to an identified stream. Valid options are:

Example: 

```json
    [...]
        {
            "vid": 42,                          # VLAN ID
            "stream_handle": 8,                 # Assigned stream handle
            "eth_dst": "ff:ff:ff:ff:ff:ff",     
            "ipv4_src": "10.1.1.2",
            "ipv4_dst": "10.1.1.2",
            "ipv4_diffserv": 0,
            "ipv4_prot": 6,
            "src_port": 4321,
            "dst_port": 4321,
            "stream_block_enable": true         # Enables permanent block for exceeding the max SDU
        },
    [...]
```

#### Stream Filter

Example: 

```json
    [...]
        {
            "stream_handle": 7,             # Assigned by Stream ID
            "stream_gate_instance": 2,      # ID of this gate
            "max_sdu": 1500,                
            "pcp": "*",                     # Either 0-7 or *
            "flow_meter_instance": 200      # Assigned flow meter
        },
    [...]
```

#### Stream Gate

Example: 

```json
    [...]
        {
            "stream_gate_id": 1,
            "ipv": 8,                   # 8 means keep PCP
            "schedule": "OPEN",
            "gate_closed_due_to_invalid_rx_enable": false,
            "gate_closed_due_to_octets_exceeded_enable": false
        },
    [...]
```

#### Stream Gate Control List

The stream gate control list contains all time slices, associated with the IPV, max octets and gate state. Note that time slices in the closed (0) gate state do not need to be stated explicitly.
For the sake of clarity, they are contained in the following example. All time values are in nanoseconds.
Time slices are truncated to values between 2 μs and 2.1 s.

Example:

```json
    [...]   
        {
            "name": "1-4-2-1",
            "period": 800000000,
            "intervals": [
                {
                    "low": 0,
                    "high": 100000000,
                    "state": 1,
                    "ipv": 2,
                    "octets": 500000
                },
                {
                    "low": 100000000,
                    "high": 500000000,
                    "state": 0,
                    "ipv": 3,
                    "octets": 500000
                },
                {
                    "low": 500000000,
                    "high": 700000000,
                    "state": 1,
                    "ipv": 5,
                    "octets": 500000
                },
                {
                    "low": 700000000,
                    "high": 800000000,
                    "state": 0,
                    "ipv": 8,
                    "octets": 500000
                }
            ]
        },
    [...]
```

#### Schedule to Port Mapping

A schedule needs to be assigned to one (or more) specific ingress ports to allow for periodicity.
Multiple schedules on the same port must form a hyperperiod.

Example: 

```json
    [...]
    "schedule_to_port": [
        {
            "schedule": "FIFTYFIFTY",
            "port": 180
        },
    ]
    [...]
```

#### Flow Meter

Example: 
```json
    [...]
        {
            "flow_meter_id": 100,
            "cir_kbps": 510000,
            "pir_kbps": 720000,
            "cbs": 1000,
            "pbs": 2000,
            "drop_yellow": false,
            "mark_red": false,
            "color_aware": false
        },
    [...]
```

### Time synchronization

A highly synchronized control plane is assumed. 
The data plane is synchronized to the control plane regarding clock drifts and differences between physical ingress ports.
If gate control lists between differenct physical ingress ports need to synchronized, the `switch.pkt_gen.get_epsilon_2_between_periods` function has to be called. See below for an example:

```py
def delta_adjustment_thread(switch):
    # Difference in hyperperiod timestamps between ports
    # Initialize for Port 32 and Port 40
    epsilon_2_p32_40 = 0
    sleep(1)

    while True:  
        switch.pkt_gen.get_epsilon_1_clock_drift()
        epsilon_2_p32_40 = switch.pkt_gen.get_epsilon_2_between_periods(epsilon_2_p32_40, 32, 40)

        for _, d in switch.pkt_gen.app_id_mapping.items():
            if d['port'] and d['port'] == 180:
                logging.info(f"{d['port']}: ε1={d['Delta']['epsilon_1']}, ε2={d['Delta']['epsilon_2']}")

        switch.pkt_gen.delta_adjustment()
        sleep(.1)
```

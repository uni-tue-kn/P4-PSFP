#!/usr/bin/env python3
import sys
from time import sleep
import threading
import multiprocessing
import argparse

sys.path.append("/opt/bf-sde-9.9.0/install/lib/python3.8/site-packages/tofino")
sys.path.append("/opt/bf-sde-9.9.0/install/lib/python3.8/site-packages/tofino/bfrt_grpc")
sys.path.append("/opt/bf-sde-9.9.0/install/lib/python3.8/site-packages")
sys.path.append("/opt/bf-sde-9.9.0/install/lib/python3.8/site-packages/bf-ptf")

from libs.PortManager import PortManager
from libs.Switch import Switch, TerminalColor

import logging
from scapy.all import *
from libs import Helper
from libs.controller.StreamFilterController import StreamFilterController
from libs.controller.StreamGateController import StreamGateController
from libs.controller.FlowMeterController import FlowMeterController
from simulation import Simulation
from libs.configuration import Config

from conn_mgr_pd_rpc.ttypes import *
from ptf.thriftutils import *
from res_pd_rpc.ttypes import *
from pal_rpc.ttypes import *
import bfrt_grpc.client as gc


logging.basicConfig(level=logging.INFO, datefmt='%d.%m.%Y %I:%M:%S', format='[%(levelname)s] %(asctime)s %(message)s')

def main():

    parser = argparse.ArgumentParser(description="Control plane")
    parser.add_argument('-c' , '--config', default="configuration.json", action='store', type=str, help="Config file to load.")
    args = parser.parse_args()

    s1 = Switch(name="s1", ip="127.0.0.1", grpc_port=50052, thrift_port=9090, program="sdn-psfp", clear=False)
    pm = PortManager(switch=s1)

    # Reset table data
    s1.delete_all_table_data()


    hosts = [{"name": "carrie-host", "auto_neg_in": 2, "port": 7, "internal_port": pm.get_port_id(7), "recirculation_port": 26, "ipv4_dst": "10.1.1.2", "mac_dst": "00:0f:53:73:e6:70", "egress_port": 7, "auto_neg_eg": 2, "internal_egress_port": pm.get_port_id(7)},
             {"name": "p4tg-voip", "auto_neg_in": 0,"port": 8, "internal_port": pm.get_port_id(8), "recirculation_port": 25, "ipv4_dst": "1.2.3.5", "mac_dst": "de:ad:be:ef:de:ad", "egress_port": 8, "auto_neg_eg": 0, "internal_egress_port": pm.get_port_id(8)},
             {"name": "p4tg-bulk", "auto_neg_in": 0,"port": 11, "internal_port": pm.get_port_id(11), "recirculation_port": 17, "ipv4_dst": "5.6.7.8", "mac_dst": "de:ad:be:ef:de:ad", "egress_port": 11, "auto_neg_eg": 0, "internal_egress_port": pm.get_port_id(11)},
             {"name": "p4tg-bulk2", "auto_neg_in": 0,"port": 12, "internal_port": pm.get_port_id(12), "recirculation_port": 18, "ipv4_dst": "1.2.3.4", "mac_dst": "de:ad:be:ef:de:ad", "egress_port": 11, "auto_neg_eg": 0, "internal_egress_port": pm.get_port_id(11)}]


    config = Config(args.config)

    if config.simulate:
        logging.basicConfig(level=logging.DEBUG, datefmt='%m/%d/%Y %I:%M:%S', format='[%(levelname)s] %(asctime)s %(message)s')

    # Configure ports
    for h in hosts:
        ingress_port = h["port"]
        internal_ingress_port = h["internal_port"]
        recirc_port = h["recirculation_port"]
        internal_egress_port = h["internal_egress_port"]
        egress_port = h["egress_port"]

        # Configure ingress port
        pm.add_port(port=ingress_port, channel=0, speed=7, fec=0, auto_neg=h["auto_neg_in"])
        # Configure recirculation port
        pm.add_port(port=recirc_port, channel=0, speed=7, fec=0, auto_neg=0, loopback=True) 

        # Configure egress port
        pm.add_port(port=egress_port, channel=0, speed=7, fec=0, auto_neg=h["auto_neg_eg"]) 


        # Set recirculation port mapping
        s1.write_table_entry(table="ingress.psfp_c.mapping_ingress_recirculation_port",
                        match_fields={"ig_intr_md.ingress_port": internal_ingress_port},   
                        action_name="ingress.psfp_c.set_recirculation_port",
                        action_params={"recirc_port": pm.get_port_id(recirc_port)})

        # Configure IPv4 Forwarding
        s1.write_table_entry(table="ingress.ipv4_c.ipv4",
                match_fields={"hdr.ipv4.dstAddr": (h["ipv4_dst"], 32, "lpm")},   
                action_name="ingress.ipv4_c.ipv4_forward",
                action_params={"eth_dst_addr": Helper.str_to_mac(h["mac_dst"]),       
                "port": internal_egress_port})
  
    #pm.add_port(port=7, channel=0, speed=7, fec=0, auto_neg=2) # disable auto negotiation for this port

    # ! P4TG Eval specific
    #push_vlan_headers(s1, hosts[1]["internal_port"], 1337)
    #push_vlan_headers(s1, hosts[2]["internal_port"], 1337)
    #push_vlan_headers(s1, hosts[3]["internal_port"], 1337)

            
    # Creates table entries for Filter, Gate and Meters
    s1.stream_filter_controller = StreamFilterController(s1, config.instances_streams, config.instances_filters)
    s1.stream_filter_controller.create_table_entries()

    s1.stream_gate_controller = StreamGateController(s1, config.instances_gates, config)

    s1.flow_meter_controller = FlowMeterController(s1, config.instances_flow_meters)
    s1.flow_meter_controller.write_meter_table()

    # Initialize pkt generator for hyperperiods
    s1.init_pktgen()

    app_id=0
    for p in config.schedule_port_mappings:
        # There can be multiple schedules per port, as long as they share the same hyperperiod
        # There can only be 8 different hyperperiods.
        s1.pkt_gen.configure_pkt_gen(app_id=app_id, period=p["period"], port=p["port"])
        app_id += 1

    s1.init_underflow_detection_table()
    s1.pkt_gen.init_clock_drift_offset_detection_table()

    #s1.dump_table("ingress.ipv4_c.ipv4")

    # ----------------------- Hyperperiods ------------------------
    #print(s1.read_register(register_name="ingress.psfp_c.hyperperiod_done", register_index=188)[0])
    #print(s1.read_register(register_name="ingress.psfp_c.period_count", register_index=180)[0])

    # -------------------- StreamFilter tables --------------------
    #s1.dump_table("ingress.psfp_c.streamFilter_c.stream_id")
    #s1.dump_table("ingress.psfp_c.streamFilter_c.stream_filter_instance")
    #print(s1.read_register(register_name="ingress.psfp_c.streamFilter_c.reg_filter_blocked", register_index=7)[0])
    #s1.dump_table("ingress.psfp_c.streamFilter_c.max_sdu_filter")
    #s1.dump_table("ingress.psfp_c.streamFilter_c.stream_id_active")
    #print(s1.read_register(register_name="ingress.psfp_c.streamFilter_c.reg_filter_blocked", register_index=7)[0])

    # --------------------- StreamGate tables ---------------------
    #s1.dump_table("ingress.psfp_c.streamGate_c.stream_gate_instance")
    #s1.dump_table("ingress.psfp_c.streamGate_c.stream_gate_config")
    #print(s1.get_counter_at_index("ingress.psfp_c.streamGate_c.missed_interval_counter", 2))
    #print(s1.read_register(register_name="ingress.psfp_c.streamGate_c.reg_gate_blocked", register_index=2)[0])
    #print(s1.read_register(register_name="ingress.psfp_c.streamGate_c.state_reset_octets", register_index=3)[0])
    #print(s1.read_register(register_name="ingress.psfp_c.streamGate_c.first_sdu_per_interval", register_index=3)[0])
    #print(s1.read_register(register_name="ingress.psfp_c.streamGate_c.octets_per_interval", register_index=3)[0])

    # --------------------- FlowMeter tables ----------------------
    #s1.dump_table("ingress.psfp_c.flowMeter_c.flow_meter_instance")
    #s1.dump_table("ingress.psfp_c.flowMeter_c.flow_meter_config")
    #print(s1.read_register(register_name="ingress.psfp_c.flowMeter_c.reg_meter_blocked", register_index=100)[0])
    #print(s1.get_counter_at_index("ingress.psfp_c.flowMeter_c.marked_red_counter", 100))
    #print(s1.get_counter_at_index("ingress.psfp_c.flowMeter_c.marked_yellow_counter", 100))
    #print(s1.get_counter_at_index("ingress.psfp_c.flowMeter_c.marked_green_counter", 100))

    # --------------------- Packet generator ----------------------
    #s1.dump_table("ingress.psfp_c.timed_pkt")
    #s1.dump_table("ingress.psfp_c.app_id_port")
    #s1.dump_table("ingress.psfp_c.port_to_hyperperiod")
    #s1.pkt_gen.get_pkt_gen_config()

    # -------------------- Clock drift offset ---------------------
    #s1.dump_table("egress.decide_shift_dir")
    #s1.dump_table("egress.map_offset_shift_right")
    #s1.dump_table("egress.map_offset_shift_left")

    # --------------------- Indirect Counters ---------------------
    #s1.dump_table("ingress.psfp_c.streamFilter_c.missed_max_sdu_filter_counter")
    #s1.dump_table("ingress.psfp_c.streamGate_c.not_passed_gate_counter")
    #s1.dump_table("ingress.psfp_c.flowMeter_c.marked_red_counter")

    # -------------------- Underflow detection --------------------
    #s1.dump_table("ingress.port_to_hyperperiod")
    #s1.dump_table("egress.underflow_detection")
    #s1.dump_table("egress.decide_shift_dir")

    # Threads for receiving digests
    t1 = threading.Thread(target=s1.listen_for_digests, args=(), daemon=True, name="Digest-Listener")
    t1.start()

    t2 = threading.Thread(target=delta_adjustment_thread, args=(s1,), daemon=True, name="Delta-Adjustment")
    t2.start()

    logging.info(f"{TerminalColor.RED.value}----------------------------- WAIT FOR FIRST HYPERPERIOD TO FINISH ----------------------------{TerminalColor.DEFAULT.value}")

    if config.simulate:

        # Start a monitoring session
        s1.sim = Simulation(s1, 
                            json_file=config.simulation_json_file,
                            csv_file=config.simulation_csv_file,
                            simulation_duration=config.simulation_duration, 
                            stream_gate_id=config.monitor_stream_gate_id,
                            flow_meter_id=config.monitor_flow_meter_id)
        try:
            while not s1.sim.exit_flag:
                sleep(1)
            #s1.sim.dump_eval_p4tg_counters_meter()
            s1.sim.analyze_stream_gate_data()
        except KeyboardInterrupt:
            s1.sim.exit_flag = True
            s1.shutdown()
            exit(0)
    else:
        try:
            while True:  

                s1.dump_table("ingress.psfp_c.streamGate_c.stream_gate_instance")
                print(s1.get_counter_at_index("ingress.psfp_c.streamGate_c.missed_interval_counter", 2))
                #print(s1.read_register(register_name="ingress.psfp_c.streamGate_c.reg_gate_blocked", register_index=2)[0])
                #print(s1.get_counter_at_index("ingress.psfp_c.flowMeter_c.marked_red_counter", 100))
                #print(s1.get_counter_at_index("ingress.psfp_c.flowMeter_c.marked_yellow_counter", 100))
                #print(s1.get_counter_at_index("ingress.psfp_c.flowMeter_c.marked_green_counter", 100))
                #print(s1.read_register(register_name="ingress.psfp_c.flowMeter_c.reg_meter_blocked", register_index=100)[0])

                #print(s1.pkt_gen.read_hyperperiod_register(180))

                #s1.dump_table("egress.decide_shift_dir")
                #s1.dump_table("egress.map_offset_shift_right")
                #s1.dump_table("egress.map_offset_shift_left")
                #s1.dump_table("egress.offset_detection_shift_left")
                #s1.dump_table("ingress.ipv4_c.ipv4")

                # Keeping the control plane alive
                sleep(1)
        except KeyboardInterrupt:
            #s1.dump_table("ingress.psfp_c.flowMeter_c.evaluation_p4tg")
            #print(queue_data)
            s1.shutdown()
            exit(0)
    
    s1.shutdown()


def push_vlan_headers(switch, port, vid):
    switch.write_table_entry(table="ingress.push_802_1q_header",
                match_fields={"ig_intr_md.ingress_port": port},   
                action_name="ingress.push_vlan_header",
                action_params={"vid": vid})

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

main()

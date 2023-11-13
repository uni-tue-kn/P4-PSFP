import time
import threading
import matplotlib.pyplot as plt
import logging
import json
import csv

from libs.Switch import Switch, TerminalColor


class Simulation(object):
    """
    This class starts a simulation which collects data from all flow meter externs and saves them to the provided location.
    The simulation and control plane is terminated after simulation_duration seconds.
    """

    def __init__(self, switch: Switch, json_file: str, csv_file: str, simulation_duration: int, flow_meter_id: int = None, stream_gate_id: int = None) -> None:
        self.switch = switch
        self.exit_flag = False
        self.running = False
        self.flow_meter_id = flow_meter_id
        self.stream_gate_id = stream_gate_id

        # Files to save data to.
        self.json_file = json_file
        self.csv_file = csv_file
        #self.csv_file = None
        self.simulation_duration = simulation_duration
        # Flag if simulation should be plotted in real time
        self.do_plot = False
        
        self.data_points = []
        self.data_points_gate = []

    def start_sim(self):
        """
        Start the simulation. This function is called once the first hyperperiod is done.
        Monitoring flow meter and stream gate is an exclusive or.
        """

        if self.flow_meter_id:
            logging.info(f"Monitoring thread for {self.flow_meter_id=} started.")
            t1 = threading.Thread(target=self.monitor_flow_meter, args=(), daemon=True, name="Flow-Meter-Monitor")
            t1.start()
        elif self.stream_gate_id:
            logging.info(f"Monitoring for {self.stream_gate_id} started.")
            t1 = threading.Thread(target=self.collect_stream_gate_data, args=(), daemon=True, name="Stream-Gate-Monitor")
            t1.start() 
        self.running = True

    def update_data(self, new_data):
        """
        This function appends the collected new_data to the given file, or creates it if it doesnt exist.

        :param new_data: list of dicts with the data to be appended to the json file
        """
        try:
            with open(self.json_file, 'r+') as file:
                file_data = json.load(file)
                file_data += [new_data]
                print(f"Simulation {len(file_data)} complete!")
                j = json.dumps(file_data)
                file.seek(0)
                file.write(j)
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            file = open(self.json_file, "w")
            file.write("[]")
            file.close()
            self.update_data(new_data)

    def dump_schedule_counters(self, duration):
        """
        This function dumps the PKT counter externs of the stream gate instance at the end of a simulation run
        and appends them to a csv file.
        """
        self.switch.sync_counters('ingress.psfp_c.streamGate_c.stream_gate_instance')

        entries = self.switch.get_table_entries("ingress.psfp_c.streamGate_c.stream_gate_instance")
        all_rows = []
        for k, v in entries:
            actions = k.to_dict()
            matches = v.to_dict()
            # Merge both dicts into one
            row = {**matches, **actions}
            all_rows.append(row)
        # Filter out intervals of this gate id
        gate_rows = list(filter(lambda r: r["ig_md.stream_filter.stream_gate_id"] == {'value': self.stream_gate_id}, all_rows))
        pkt_counts = [duration] + [interval['$COUNTER_SPEC_PKTS'] for interval in gate_rows]

        with open(self.csv_file, 'a+', encoding='UTF8', newline='') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(pkt_counts)

    def collect_stream_gate_data(self):
        """
        This function synchronizes and reads the counter values from the stream gate instance table.
        Reading the values takes ~150ms, thus this is the sampling rate.
        Counter values are stored as generators, as evaluating those would take too long during runtime.
        Analyze the generators with the analyze_stream_gate_data functions at the end of a simulation.
        """

        start_ts = time.time()

        while not self.exit_flag:
            # Synchonize counters first
            self.switch.sync_counters('ingress.psfp_c.streamGate_c.stream_gate_instance')

            entries = self.switch.get_table_entries("ingress.psfp_c.streamGate_c.stream_gate_instance")

            ts = time.time()
            duration = ts - start_ts
            dp = {"ts": ts, "data": entries}
            self.data_points_gate.append(dp)
            
            if duration > self.simulation_duration:
                print(f"{self.simulation_duration}s simulation done!")
                if self.csv_file:
                    self.dump_schedule_counters(duration)
                self.exit_flag = True
            #time.sleep(0.05)

    def analyze_stream_gate_data(self):
        """
        This function analyzes the data_points collected as generator objects in the 
        self.data_points_gate variable collected by the collect_stream_gate_data function.
        """
        total_pkts = 0
        forwarded_pkts = 0
        data = []
        for dp in self.data_points_gate:
            entries = dp["data"]
            pkts = []
            for k, v in entries:
                values = v.to_dict()
                keys = k.to_dict()

                if values['ig_md.stream_filter.stream_gate_id']['value'] == self.stream_gate_id:
                    pkts.append([keys['$COUNTER_SPEC_PKTS'], keys['gate_state']])
            
            total_pkts = sum([x[0] for x in pkts])
            forwarded_pkts = sum(x[0] for x in pkts if x[1] == 1)
            data.append({"ts": dp['ts'], "sent_packets": total_pkts, "pkt_count_green": forwarded_pkts})
        self.update_data(data)

    def dump_eval_p4tg_counters(self):
        self.switch.sync_counters('ingress.psfp_c.flowMeter_c.evaluation_p4tg')

        entries = self.switch.get_table_entries("ingress.psfp_c.flowMeter_c.evaluation_p4tg")
        data = []
        for k, v in entries:
            actions = k.to_dict()
            matches = v.to_dict()
            row = {"interval": matches["hdr.recirc_time.orig_ts"], "frames": actions["$COUNTER_SPEC_PKTS"]}
            data.append(row)
        self.update_data(data)

    def dump_eval_p4tg_counters_meter(self):
        self.switch.sync_counters('ingress.psfp_c.flowMeter_c.evaluation_p4tg')

        entries = self.switch.get_table_entries("ingress.psfp_c.flowMeter_c.evaluation_p4tg")
        data = []
        for k, v in entries:
            actions = k.to_dict()
            matches = v.to_dict()
            row = {"interval": matches["hdr.recirc_time.orig_ts"], "frames": actions["$COUNTER_SPEC_PKTS"], "color": matches["ig_tm_md.packet_color"]["value"], "bytes": actions["$COUNTER_SPEC_BYTES"]}
            data.append(row)
        self.update_data(data)

    def monitor_flow_meter(self):
        last_green_bytes = 0
        last_yellow_bytes = 0
        last_red_bytes = 0
        last_overall_bytes = 0
        last_ts = 0
        start_ts = time.time()

        while not self.exit_flag:
            ts = time.time()

            # TODO slow performance when reading counters with from_hw=true in SDE 9.9.0
            green_counter = self.switch.get_counter_at_index("ingress.psfp_c.flowMeter_c.marked_green_counter", self.flow_meter_id)
            yellow_counter = self.switch.get_counter_at_index("ingress.psfp_c.flowMeter_c.marked_yellow_counter", self.flow_meter_id)
            red_counter = self.switch.get_counter_at_index("ingress.psfp_c.flowMeter_c.marked_red_counter", self.flow_meter_id)
            overall_counter = self.switch.get_counter_at_index("ingress.psfp_c.streamFilter_c.overall_counter", self.flow_meter_id)

            # Remove recirculation header size
            green_bytes = green_counter["$COUNTER_SPEC_BYTES"] - green_counter["$COUNTER_SPEC_PKTS"] * 7  
            yellow_bytes = yellow_counter["$COUNTER_SPEC_BYTES"] - yellow_counter["$COUNTER_SPEC_PKTS"] * 7
            red_bytes = red_counter["$COUNTER_SPEC_BYTES"] - red_counter["$COUNTER_SPEC_PKTS"] * 7
            overall_bytes = overall_counter["$COUNTER_SPEC_BYTES"] - overall_counter["$COUNTER_SPEC_PKTS"] * 7
            #overall_bytes = green_bytes + red_bytes + yellow_bytes
            time_delta = ts - last_ts
            duration = ts - start_ts

            # Calculate bandwidths
            green_rate = round((green_bytes - last_green_bytes) * 8 / 1000000000 / time_delta, 2)
            yellow_rate = round((yellow_bytes - last_yellow_bytes) * 8 / 1000000000 / time_delta, 2)
            red_rate = round((red_bytes - last_red_bytes) * 8 / 1000000000 / time_delta, 2)

            send_rate = round((overall_bytes - last_overall_bytes) * 8 / 1000000000 / time_delta, 2)
            
            logging.debug(f"{TerminalColor.GREEN.value}{green_rate=}kbps{TerminalColor.DEFAULT.value}, " 
                    f"{TerminalColor.YELLOW.value}{yellow_rate=}kbps{TerminalColor.DEFAULT.value}, "
                    f"{TerminalColor.RED.value}{red_rate=}kbps{TerminalColor.DEFAULT.value}, "
                    f"{TerminalColor.BLUE.value}{send_rate=}kbps{TerminalColor.DEFAULT.value}")

            last_overall_bytes = overall_bytes
            last_green_bytes = green_bytes
            last_yellow_bytes = yellow_bytes
            last_red_bytes = red_bytes
            last_ts = ts

            data_point = {"seconds": duration, "green_rate": green_rate, "yellow_rate": yellow_rate, "red_rate": red_rate, "send_rate": send_rate}
            self.data_points.append(data_point)

            if duration > self.simulation_duration:
                print(f"{self.simulation_duration}s simulation done!")
                duration = str(duration).replace('.', ",")
                self.update_data(self.data_points)
                self.exit_flag = True

            if self.do_plot:
                t = threading.Thread(target=self.plot_bandwidth, args=(self.data_points,), daemon=True, name="Plotter")
                t.start()

            #time.sleep(.25)
    def plot_bandwidth(self, data_points: list):

        #plt.clf()
        plt.figure(figsize=(1920/100, 1440/100))
        #plt.figure()
        plt.rc('axes', titlesize=25)
        plt.rc('axes', labelsize=25)
        plt.rc('xtick', labelsize=22)
        plt.rc('ytick', labelsize=22)
        plt.rc('legend', fontsize=24)
        plt.xlabel("Time in s")
        plt.ylabel("Bandwidth in mbps")

        #plt.title("Bandwidths")
        #x_axis = [idx for idx, d in enumerate(data_points)]
        x_axis = [d['seconds'] for d in data_points]

        green_rate = [d['green_rate'] for d in data_points]
        yellow_rate = [d['yellow_rate'] for d in data_points]
        red_rate = [d['red_rate'] for d in data_points]
        send_rate = [d['send_rate'] for d in data_points]
        cir = [700 for _ in range(len(x_axis))]
        eir = [100 for _ in range(len(x_axis))]


        plt.plot(x_axis, green_rate, label="Green Rate", color="green", marker="o", linewidth=3)
        plt.plot(x_axis, yellow_rate, label="Yellow Rate", color="orange", marker="o", linewidth=3)
        plt.plot(x_axis, red_rate, label="Dropping Rate", color="red", marker="o", linewidth=3)
        plt.plot(x_axis, send_rate, label="Sending Rate", color="blue", marker="o", linewidth=3)
        plt.plot(x_axis, eir, label="Excess Information Rate (EIR)", color="orange", linestyle='dotted', linewidth=3)
        plt.plot(x_axis, cir, label="Committed Information Rate (CIR)", color="green", linestyle='dotted', linewidth=3)

        plt.legend()
        plt.savefig("bandwidth.png")
        plt.close()
import json
from libs.instances.instances import FlowMeterInstance, StreamFilterInstance, StreamGateInstance, StreamID, Schedule


class Config:

    def __init__(self, config_file: str):
        self.config_file = config_file
        self.instances_streams = []
        self.instances_schedules = []
        self.instances_filters = []
        self.instances_gates = []
        self.instances_flow_meters = []
        self.schedule_port_mappings = []

        self.simulate = False
        self.simulation_duration = 4
        self.simulation_json_file = "plots/data/data.json"

        self.parse_config_params()
        self.validate_config()

    def parse_config_params(self):
        """
        Reads the configuration parameters from the specified file
        """

        with open(self.config_file) as file:
            data = json.load(file)

        simulation = data["simulation"]
        schedules = data["gate_schedules"]
        streams = data["streams"]
        stream_filters = data["stream_filters"]
        stream_gates = data["stream_gates"]
        flow_meters = data["flow_meters"]
        schedule_port_mappings = data["schedule_to_port"]

        self.simulate = simulation["enabled"]
        self.simulation_duration = simulation["duration"]
        self.simulation_json_file = simulation["json_file"]
        self.simulation_csv_file = simulation["csv_file"]
        self.monitor_flow_meter_id = simulation["monitor_flow_meter_id"]
        self.monitor_stream_gate_id = simulation["monitor_stream_gate_id"]

        for s in schedules:
            instance = Schedule(name=s["name"],
                                intervals=s["intervals"],
                                period=s["period"],
                                time_shift=s["time_shift"])
            self.instances_schedules.append(instance)

        for s in streams:
            eth_dst = s["eth_dst"] if "eth_dst" in s.keys() else None
            eth_src = s["eth_src"] if "eth_src" in s.keys() else None
            ipv4_src = s["ipv4_src"] if "ipv4_src" in s.keys() else None
            ipv4_dst = s["ipv4_dst"] if "ipv4_dst" in s.keys() else None
            ipv4_diffserv = s["ipv4_diffserv"] if "ipv4_diffserv" in s.keys(
            ) else None
            ipv4_prot = s["ipv4_prot"] if "ipv4_prot" in s.keys() else None
            src_port = s["src_port"] if "src_port" in s.keys() else None
            dst_port = s["dst_port"] if "dst_port" in s.keys() else None
            active = s["active"] if "active" in s.keys() else False
            overwrite_eth_dst = s["overwrite_eth_dst"] if "overwrite_eth_dst" in s.keys(
            ) else None
            overwrite_vid = s["overwrite_vid"] if "overwrite_vid" in s.keys(
            ) else None
            overwrite_pcp = s["overwrite_pcp"] if "overwrite_pcp" in s.keys(
            ) else None

            instance = StreamID(vid=s["vid"],
                                stream_handle=s["stream_handle"],
                                stream_block_enable=s["stream_block_enable"],
                                eth_dst=eth_dst,
                                eth_src=eth_src,
                                ipv4_src=ipv4_src,
                                ipv4_dst=ipv4_dst,
                                ipv4_diffserv=ipv4_diffserv,
                                ipv4_prot=ipv4_prot,
                                src_port=src_port,
                                dst_port=dst_port,
                                active=active,
                                overwrite_eth_dst=overwrite_eth_dst,
                                overwrite_vid=overwrite_vid,
                                overwrite_pcp=overwrite_pcp)

            self.instances_streams.append(instance)

        for g in stream_gates:
            instance = StreamGateInstance(gate_id=g["stream_gate_id"],
                                          ipv=g["ipv"],
                                          schedule=self.find_schedule_by_name(
                                              g["schedule"]),
                                          gate_closed_due_to_invalid_rx_enable=g[
                                              "gate_closed_due_to_invalid_rx_enable"],
                                          gate_closed_due_to_octets_exceeded_enable=g["gate_closed_due_to_octets_exceeded_enable"])
            self.instances_gates.append(instance)

        for m in flow_meters:
            instance = FlowMeterInstance(flow_meter_id=m["flow_meter_id"],
                                         cir_kbps=m["cir_kbps"],
                                         pir_kbps=m["pir_kbps"],
                                         cbs=m["cbs"],
                                         pbs=m["pbs"],
                                         dropOnYellow=m["drop_yellow"],
                                         markAllFramesRedEnable=m["mark_red"],
                                         colorAware=m["color_aware"])
            self.instances_flow_meters.append(instance)

        for f in stream_filters:
            instance = StreamFilterInstance(stream_handle=f["stream_handle"],
                                            stream_gate=self.find_gate_instance_by_id(
                                                f["stream_gate_instance"]),
                                            max_sdu=f["max_sdu"],
                                            pcp=f["pcp"],
                                            flow_meter=self.find_flow_meter_instance_by_id(f["flow_meter_instance"]))
            self.instances_filters.append(instance)

        for p in schedule_port_mappings:
            schedule = self.find_schedule_by_name(p["schedule"])
            self.schedule_port_mappings.append(
                {"schedule": schedule.name, "period": schedule.period, "port": p["port"]})

    def find_gate_instance_by_id(self, gate_id):
        result = [g for g in self.instances_gates if g.gate_id == gate_id]
        if result:
            return result[0]
        raise AssertionError(f"Stream gate instance {gate_id=} is undefined!")

    def find_flow_meter_instance_by_id(self, meter_id):
        result = [
            f for f in self.instances_flow_meters if f.flow_meter_id == meter_id]
        if result:
            return result[0]
        raise AssertionError(f"Flow meter instance {meter_id=} is undefined!")

    def find_schedule_by_name(self, name):
        result = [s for s in self.instances_schedules if s.name == name]
        if result:
            return result[0]
        raise AssertionError(f"Schedule {name=} is undefined!")

    def validate_config(self):
        meter_ids = [m.flow_meter_id for m in self.instances_flow_meters]
        stream_handles = [s.stream_handle for s in self.instances_filters]
        gate_ids = [g.gate_id for g in self.instances_gates]
        schedule_names = [s.name for s in self.instances_schedules]

        # Assert that every id is only defined once
        assert len(meter_ids) == len(set(meter_ids))
        assert len(stream_handles) == len(set(stream_handles))
        assert len(gate_ids) == len(set(gate_ids))
        assert len(schedule_names) == len(set(schedule_names))

        # Assert that referenced instances exist
        referenced_schedules = [g.schedule.name for g in self.instances_gates] + [
            p["schedule"] for p in self.schedule_port_mappings]
        referenced_gates = [
            s.stream_gate.gate_id for s in self.instances_filters]
        referenced_meters = [
            s.flow_meter.flow_meter_id for s in self.instances_filters]

        # Assert that only one period is assigned to a port
        ports = [p["port"] for p in self.schedule_port_mappings]

        assert len(ports) == len(set(ports))

        for s in referenced_schedules:
            assert self.find_schedule_by_name(s) != None
        for g in referenced_gates:
            assert self.find_gate_instance_by_id(g) != None
        for m in referenced_meters:
            assert self.find_flow_meter_instance_by_id(m) != None

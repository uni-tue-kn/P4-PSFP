from bfrt_grpc.client import ClientInterface
import bfrt_grpc.client as gc
from . import Helper
import re
from prettytable import PrettyTable
from enum import Enum
from typing import Optional

from libs.ThriftConnection import ThriftConnection
from thrift.protocol import TBinaryProtocol, TMultiplexedProtocol

from libs.PktGen import PktGen

import logging
import importlib


class TerminalColor(Enum):
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    RED = '\033[31m'
    BLUE = '\033[34m'
    PINK = '\033[95m'
    DEFAULT = '\033[m'


class DigestType(Enum):
    MAXSDUEXCEEDED = 1
    INVALIDRX = 2
    MARKEDRED = 3
    HYPERPERIOD = 6


# Color list for flow meter coloring according to P4 implementation
COLORS = [TerminalColor.GREEN.value, TerminalColor.YELLOW.value,
          TerminalColor.YELLOW.value, TerminalColor.RED.value, TerminalColor.DEFAULT.value]


class Switch:
    """
    This class represents a PSFP enabled switch object.
    """

    def __init__(self, name: str = "", ip: str = "127.0.0.1", grpc_port: int = 50052, thrift_port: int = 9090, clear: bool = True, program: str = ""):
        self.name = name
        self.grpc_addr = ip + ":" + str(grpc_port)
        self.thrift = ThriftConnection(ip=ip, port=thrift_port)
        self.pkt_gen = PktGen(self)
        self.stream_filter_controller = None
        self.stream_gate_controller = None
        self.flow_meter_controller = None

        # Calculated value that is the difference from the control plane to the data plane time.
        self.delta = 0

        # Simulation monitoring session
        self.sim = None

        # ! Hardcoded Digest IDs
        self.digests = {"2397224885": "digest_pktgen",
                        "2387156053": "digest_hyperperiod",
                        "2386104925": "digest_debug_gate"}

        self.c = ClientInterface(self.grpc_addr, 1, 0)
        self.c.bind_pipeline_config(program)

        # pal
        self.pal_client_module = importlib.import_module(
            ".".join(["pal_rpc", "pal"]))
        self.pal = self.pal_client_module.Client(
            TMultiplexedProtocol.TMultiplexedProtocol(self.thrift.protocol, "pal"))

        if clear:
            self.c.clear_all_tables()

        self.bfrt_info = self.c.bfrt_info_get()
        self.target = gc.Target(device_id=0, pipe_id=0xffff)

    def init_pktgen(self):
        """
        Configure the packet generator.
        """
        self.pkt_gen.set_up_pkt_gen()

    def write_table_entry(self, table: str = "", match_fields: Optional[dict] = None, action_name: str = "", action_params: Optional[dict] = None):
        """
        Creates a table entry in the data plane.

        :param table: str, Name of the table.
        :param match_fields: dict, pairs of key:value in MAT.
        :param action_name: str, name of the action to apply.
        :param action_params: dict, pairs of key:value in action definition.
        """
        bfrt_table = self.bfrt_info.table_get(table)

        keys = []

        for m in match_fields:
            if type(match_fields.get(m)) is tuple:
                if re.match(r"(\b25[0-5]|\b2[0-4][0-9]|\b[01]?[0-9][0-9]?)(\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)){3}", str(match_fields.get(m)[0])):
                    # Do IPv4 LPM if first argument of tuple is a IPv4 address
                    bfrt_table.info.key_field_annotation_add(m, "ipv4")

                if re.match(r"^[a-fA-F0-9]{2}(:[a-fA-F0-9]{2}){5}$", str(match_fields.get(m)[0])):
                    v = Helper.str_to_mac(match_fields.get(m)[0])
                    k = match_fields.get(m)[1]
                else:
                    v = match_fields.get(m)[0]
                    k = match_fields.get(m)[1]

                try:
                    if match_fields.get(m)[2] == "lpm":
                        keys.append(gc.KeyTuple(m, value=v, prefix_len=k))
                    elif match_fields.get(m)[2] == "t":
                        keys.append(gc.KeyTuple(m, value=v, mask=k))
                    elif match_fields.get(m)[2] == "r":
                        keys.append(gc.KeyTuple(m, low=v, high=k))
                    else:
                        raise KeyError
                except (IndexError, KeyError):
                    raise KeyError(
                        "No or wrong matching type specified! Use either 'lpm', 'r' or 't' as third element in tuple m.")

            else:
                if re.match(r"^[a-fA-F0-9]{2}(:[a-fA-F0-9]{2}){5}$", str(match_fields.get(m))):
                    keys.append(gc.KeyTuple(
                        m, Helper.str_to_mac(match_fields.get(m))))

                keys.append(gc.KeyTuple(m, match_fields.get(m)))

        fields = bfrt_table.make_key(keys)

        data = []

        for a in action_params:
            data.append(gc.DataTuple(a, action_params.get(a)))

        action = bfrt_table.make_data(data, action_name)

        bfrt_table.entry_add(self.target, [fields], [action])

        logging.debug("Writing table entry on {} for {}: {} with action {} and params {}".format(self.name, table,
                                                                                                 str(
                                                                                                     match_fields),
                                                                                                 str(
                                                                                                     action_name),
                                                                                                 str(action_params)))

    def remove_table_entry(self, table: str = "", match_fields: Optional[dict] = None):
        """
        Removes an entry from a table in the data plane.

        :param table: str, Name of the table.
        :param match_fields: dict, pairs of key:value in MAT.
        """
        bfrt_table = self.bfrt_info.table_get(table)

        keys = []

        if match_fields:
            for m in match_fields:
                if type(match_fields.get(m)) is tuple:
                    keys.append(gc.KeyTuple(m, low=match_fields.get(m)[
                                0], high=match_fields.get(m)[1]))
                else:
                    keys.append(gc.KeyTuple(m, match_fields.get(m)))

            fields = [bfrt_table.make_key(keys)]
        else:
            fields = None

        bfrt_table.entry_del(self.target, fields)

        logging.debug("Deleting table entry on {} for {}: {}".format(
            self.name, table, str(match_fields)))

    def update_table_entry(self, table: str = "", match_fields: Optional[dict] = None, action_name: str = "", action_params: Optional[dict] = None):
        """
        Updates a table entry in the data plane. Searches for match fields, updates the values for actions.

        :param table: str, Name of the table.
        :param match_fields: dict, pairs of key:value in MAT.
        :param action_name: str, name of the action to apply.
        :param action_params: dict, pairs of key:value in action definition.
        """
        bfrt_table = self.bfrt_info.table_get(table)

        keys = []

        for m in match_fields:
            if type(match_fields.get(m)) is tuple:
                v = match_fields.get(m)[0]
                k = match_fields.get(m)[1]
                try:
                    if match_fields.get(m)[2] == "lpm":
                        keys.append(gc.KeyTuple(m, value=v, prefix_len=k))
                    elif match_fields.get(m)[2] == "t":
                        keys.append(gc.KeyTuple(m, value=v, mask=k))
                    elif match_fields.get(m)[2] == "r":
                        keys.append(gc.KeyTuple(m, low=v, high=k))
                    else:
                        raise KeyError
                except (IndexError, KeyError):
                    raise KeyError(
                        "No or wrong matching type specified! Use either 'lpm', 'r' or 't' as third element in tuple m.")

            else:
                keys.append(gc.KeyTuple(m, match_fields.get(m)))

        fields = bfrt_table.make_key(keys)

        data = []

        for a in action_params:
            data.append(gc.DataTuple(a, action_params.get(a)))

        action = bfrt_table.make_data(data, action_name)

        bfrt_table.entry_mod(self.target, [fields], [action])

        logging.debug("Update table entry on {} for {}: {} with action {} and params {}".format(self.name, table,
                                                                                                str(
                                                                                                    match_fields),
                                                                                                str(
                                                                                                    action_name),
                                                                                                str(action_params)))

    def get_table_entries(self, table: str = "", match_fields: Optional[dict] = None, data_fields: Optional[dict] = None):
        """
        Returns entries of a table.
        All entries if match_fields is None

        :param table: str, Name of the table.
        :param match_fields: dict, pairs of key:value in MAT.
        """
        bfrt_table = self.bfrt_info.table_get(table)

        keys = []
        data = []

        if match_fields:
            for m in match_fields:
                if type(match_fields.get(m)) is tuple:
                    v = match_fields.get(m)[0]
                    k = match_fields.get(m)[1]
                    if match_fields.get(m)[2] == "lpm":
                        keys.append(gc.KeyTuple(m, value=v, prefix_len=k))
                    elif match_fields.get(m)[2] == "t":
                        keys.append(gc.KeyTuple(m, value=v, mask=k))
                    elif match_fields.get(m)[2] == "r":
                        keys.append(gc.KeyTuple(m, low=v, high=k))
                else:
                    keys.append(gc.KeyTuple(m, match_fields.get(m)))
            fields = [bfrt_table.make_key(keys)]
        else:
            fields = None

        if data_fields:
            for action, params in data_fields.items():
                for p in params:
                    data.append(gc.DataTuple(p))
                fields_data = bfrt_table.make_data(data_field_list_in=data,
                                                   action_name=action,
                                                   get=True)
        else:
            fields_data = None

        # Needed to properly display counters in dump_table function
        # False if simulation for better performance
        from_hw_flag = False if self.sim else True

        entries = bfrt_table.entry_get(self.target,
                                       key_list=fields,
                                       flags={"from_hw": from_hw_flag},
                                       required_data=fields_data)

        return entries

    def get_counter_at_index(self, table: str, index: int):
        """
        Returns the row of a indirect counter object at index i

        :param table: The table string, normally <control_block.counter_name>
        :param index: The index of the row to retrieve

        :returns data_dict: A dict of the row with all of the counter fields.
        """

        counter_table = self.bfrt_info.table_get(table)

        #self.sync_counters(table, counter_table)

        resp = counter_table.entry_get(self.target,
                                       [counter_table.make_key(
                                           [gc.KeyTuple('$COUNTER_INDEX', index)])],
                                       {"from_hw": True},
                                       None)
        data_dict = next(resp)[0].to_dict()
        return data_dict

    def delete_all_table_data(self):
        """ 
        Deletes all entries in egress and ingress tables
        """
        all_tables = self.bfrt_info.table_name_list_get()
        in_eg_tables = list(filter(lambda s: s.startswith('pipe.ingress'), all_tables)) + \
            list(filter(lambda s: s.startswith('pipe.egress'), all_tables))
        for t in in_eg_tables:
            try:
                self.remove_table_entry(table=t)
            except gc.BfruntimeReadWriteRpcException as e:
                # Fails on registers
                logging.warning(f"{e}, continuing")
                continue
            logging.debug(f"Table entries for {t} deleted.")

    def dump_table(self, table: str):
        """
        Formats all entries of a P4 table as a string and displays it as a tabular overview.

        :param table: The table string, normally <control_block.table_name>
        """

        entries = self.get_table_entries(table)
        t = PrettyTable()
        for k, v in entries:
            # k is the action and its parameters
            actions = k.to_dict()
            # v are match fields and their values
            matches = v.to_dict()

            values = []
            # Collect match fields and format them accordingly
            for m, e in matches.items():
                if 'mask' in e:
                    # Ternary entry
                    v = (e['value'], e['mask'])
                elif 'value' in e:
                    # Exact entry
                    v = e['value']
                elif 'low' in e:
                    # Range entry
                    v = f"{e['low'], e['high']}"
                else:
                    v = e

                # if str(v) == "0" or str(v) == "0.0.0.0":
                if str(v) == "0.0.0.0":
                    v = "*"
                    values.append(v)
                elif m.startswith('hdr.ethernet.dst_addr') or m.startswith('hdr.ethernet.src_addr') or 'eth_dst_addr' == str(m):
                    values.append(f"{Helper.int_to_mac(v[0])} / {v[1]}")
                else:
                    values.append(str(v))

            # Collect action fields and format them accordingly
            if actions:
                for a, e in actions.items():
                    if a.startswith('eth_dst_addr'):
                        values.append(Helper.int_to_mac(e))
                    else:
                        values.append(str(e))

                t.add_row(values)

        # Build table header
        try:
            t.field_names = list(matches.keys()) + list(actions.keys())
            print(f"{table}:\n")
            print(t)
        except UnboundLocalError:
            print(f"Table {table} is empty!")

    def reset_register(self, register_name: str = ""):
        try:
            reg_table = self.bfrt_info.table_get(register_name)
            reg_table.entry_del(self.target)
        except (gc.BfruntimeReadWriteRpcException, KeyError) as e:
            logging.critical(f"Register {register_name} not found.")

    def read_register(self, register_name: str = "", register_index: int = 0):
        reg_table = self.bfrt_info.table_get(register_name)
        resp = reg_table.entry_get(
            self.target,
            [reg_table.make_key(
                [gc.KeyTuple('$REGISTER_INDEX', register_index)])],
            {"from_hw": True})

        return next(resp)

    def get_digest(self):

        digest = self.c.digest_get()
        try:
            digest_name = self.digests[str(digest.digest_id)]
        except KeyError:
            raise ValueError("Digest ID is not known to SwitchController!")

        # ! Names of Digest from data plane
        # ! Will not work for different structs of digests!
        learn_filter = self.bfrt_info.learn_get(digest_name)
        data_list = learn_filter.make_data_list(digest)
        data_dict = data_list[0].to_dict()

        return data_dict

    def listen_for_digests(self):
        """
        Continuously listens for digest messages and outputs them.
        Triggers the handle_digest function, which permanently closes PSFP instances.
        """

        while True:
            try:
                digest = self.get_digest()

                output = ""
                for k, v in digest.items():
                    if k == "PSFPGateEnabled":
                        color = TerminalColor.GREEN.value if v == 1 else TerminalColor.RED.value
                    elif k == "color":
                        color = COLORS[digest['color']
                                       ] if 'color' in digest else ""
                    elif k == "drop_ctl":
                        color = TerminalColor.RED.value if v == 1 else TerminalColor.GREEN.value
                    else:
                        color = TerminalColor.DEFAULT.value
                    if k == "reason":
                        v = DigestType(v).name
                    output += f"{color}{k}: {v} {TerminalColor.DEFAULT.value}"

                if "app_id" not in output:
                    # Filters out hyperperiod packets from printing
                    print(output)
                    pass
                logging.debug(output)
                self.handle_digest(digest)
            except RuntimeError as e:
                # logging.error(e)
                pass

    def handle_digest(self, digest_data: dict):
        """
        Update corresponding table entries to either block streams or gates permanently

        :param digest_data: dict
        """
        try:
            if digest_data["reason"] == DigestType.HYPERPERIOD.value:
                # Hyperperiod finished
                logging.debug(
                    f"{TerminalColor.PINK.value}Hyperperiod app_id={digest_data['app_id']}, pipe={digest_data['pipe_id']} done at ts={digest_data['ingress_ts']}.{TerminalColor.DEFAULT.value}")
                if digest_data["pipe_id"] == 1:
                    prev_hyperperiod_status = self.pkt_gen.app_id_mapping[
                        digest_data['app_id']]["hyperperiod_done"]
                    if not prev_hyperperiod_status:
                        # First period finished, write schedule and start simulation if needed.
                        self.pkt_gen.app_id_mapping[digest_data['app_id']
                                                    ]["hyperperiod_done"] = True

                        self.stream_gate_controller.write_schedule(
                            digest_data['app_id'])

                        # self.flow_meter_controller.eval_p4tg_meter_config(digest_data['ingress_ts'])
                        # self.stream_gate_controller.eval_write_schedules(digest_data['ingress_ts'])
                        #self.pkt_gen.set_clock_offset(188, 300000)

                        e = self.pkt_gen.app_id_mapping[digest_data['app_id']]
                        logging.info(
                            f"{TerminalColor.GREEN.value}----------------------------- HYPERPERIOD {digest_data['app_id']}, {e['hyperperiod_duration']}ns IS NOW READY TO PROCESS REQUESTS ----------------------------{TerminalColor.DEFAULT.value}")
                        if self.sim and not self.sim.running:
                            self.sim.start_sim()
        except KeyError as e:
            print(e)
            logging.error(f"INVALID DIGEST REASON RECEIVED: {digest_data}")
            return

    def init_underflow_detection_table(self):
        """
        Init the tables that detect an underflow.
        Those tables contain a ternary match with a very large mask to 
        mimic a max() comparison, which can result from an underflow calculation.

        Clock drift offset tables are initialized here as well. 
        """

        # Mask to filter for large values (2^38, which is around 4.5 minutes)
        #mask_max_underflow = 0b111111111100000000000000000000000000000000000000
        mask_max_underflow = 0b111111111111111000000000000000000000000000000000
        self.write_table_entry(table="egress.underflow_detection",
                               match_fields={"hdr.bridge.diff_ts": (0, mask_max_underflow, "t"),
                                             "$MATCH_PRIORITY": 0},
                               action_name="egress.nop",
                               action_params={}
                               )

        # Underflow table needed for underflow handling due to inaccuracy in packet generation
        mask_interval_switch_underflow = 0b1111111111111111111111111111111111111111111111111111111111100000
        self.write_table_entry(table="egress.underflow_detection",
                               match_fields={"hdr.bridge.diff_ts": (mask_interval_switch_underflow, mask_interval_switch_underflow, "t"),
                                             "$MATCH_PRIORITY": 1},
                               action_name="egress.reset_diff_ts",
                               action_params={}
                               )

    def sync_counters(self, table_name: str, table_object: gc._Table = None):
        """
        Perform a hardware sync operation on the switch table

        :param table_name: Name of the table to sync
        :param table_object: bfrt_info resolved table object with table_name (optional)
        """
        if not table_object:
            tbl = self.bfrt_info.table_get(table_name)
        else:
            tbl = table_object
        tbl.operations_execute(self.target, 'SyncCounters')

    def __del__(self):
        self.shutdown()

    def shutdown(self):
        logging.debug("Shutting down connection to {}".format(self.name))
        # self.pkt_gen.disable_pkt_gen()
        self.thrift.end()
        self.c.channel.close()

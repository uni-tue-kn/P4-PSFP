import logging
from pal_rpc.ttypes import *

class PortManager:
    def __init__(self, switch=None):
        self.switch = switch

    def add_port(self, port=0, channel=0, speed=0, fec=False, auto_neg=0, loopback=False):
        logging.debug(
            "Add port {}/{} speed {} autoneg {} fec {} loopback {}".format(port, channel, speed, auto_neg, fec,
                                                                           loopback))
        p_id = self.switch.pal.pal_port_front_panel_port_to_dev_port_get(
            0, port, channel)
        self.switch.pal.pal_port_del(0, p_id)

        self.switch.pal.pal_port_add(0, p_id, speed, fec)
        self.switch.pal.pal_port_an_set(0, p_id, auto_neg)
        self.switch.pal.pal_port_enable(0, p_id)

        if loopback:
            self.switch.pal.pal_port_loopback_mode_set(0, p_id, 1)

    def get_port_id(self, port=0, channel=0):
        p_id = self.switch.pal.pal_port_front_panel_port_to_dev_port_get(
            0, port, channel)

        return p_id

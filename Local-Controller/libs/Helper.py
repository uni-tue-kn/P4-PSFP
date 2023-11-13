def int_to_mac(int_s):
    """ 
    Converts an int in dec to a String representation of a MAC address
    """
    s = hex(int(int_s))[2:].zfill(12)
    count = 0
    for i in range(2, len(s), 2):
        s = s[:i + count] + ":" + s[i + count:]
        count += 1
    return s


def str_to_mac(mac):
    """
    Convert a string representation of a MAC address separated by : to an integer value
    """
    return int(mac.replace(":", ""), 16)

import subprocess
from enum import Enum
from tqdm import tqdm
import math
import csv


class StreamIDs(Enum):
    NULL_STREAM = 1
    TERNARY_SRC_DST = 2
    TERNARY_IP = 3
    EXACT_IP = 4


class TerminalColor(Enum):
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    RED = '\033[31m'
    BLUE = '\033[34m'
    PINK = '\033[95m'
    DEFAULT = '\033[m'


START_SIZE = 4096
MAX_DEPTH = 20


def run_bench_stream_id(stream_id, filter_size, stream_gate_size=2048):
    print(
        f"Running with {stream_id=} with {filter_size=}, {stream_gate_size=}")
    result = subprocess.run(
        ["make", "bench", f"CFLAGS=-D__STREAM_ID__={stream_id} -D__STREAM_ID_SIZE__={filter_size} -D__STREAM_GATE_SIZE__={stream_gate_size}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        print(f"{TerminalColor.GREEN.value}Compilation successful {stream_id=} with {filter_size=}, {stream_gate_size=}{TerminalColor.DEFAULT.value}")
        return True
    else:
        print(f"{TerminalColor.RED.value}Compilation failed {stream_id=} with {filter_size=}, {stream_gate_size=}{TerminalColor.DEFAULT.value}")
        return False


def write_results(results):
    with open('bench_results.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile, delimiter=";")
        writer.writerow(["Stream ID", "WINDOW_SUCCESS",
                        "WINDOW_FAILED", "GATE_SIZE"])
        for row in results:
            writer.writerow(row)


def bench_stream_id():
    results = []
    gate_sizes = [2048]
    for gate_size in gate_sizes:
        for stream_id in tqdm([StreamIDs.NULL_STREAM, StreamIDs.TERNARY_SRC_DST, StreamIDs.TERNARY_IP, StreamIDs.EXACT_IP]):
            success_max = 0
            failed_max = math.inf
            size = START_SIZE
            for _ in tqdm(range(MAX_DEPTH)):
                #if failed_max - success_max < 200:
                #    break
                if failed_max == success_max + 1:
                    break
                print(f"Current window [{success_max}, {failed_max}]")
                if run_bench_stream_id(stream_id.value, size, stream_gate_size=gate_size):
                    print(f"Current window [{success_max}, {failed_max}]")
                    success_max = max(success_max, size)
                    # Double size
                    new_size = int(size * 2)
                    if new_size > failed_max:
                        window_diff = failed_max - success_max
                        # Dont test larger values than already failed ones
                        new_size = success_max + int(window_diff / 2)
                    size = new_size
                else:
                    failed_max = min(failed_max, size)
                    new_size = int(size * 0.75)
                    if new_size < success_max:
                        # Dont test smaller values than already successfull ones
                        window_diff = failed_max - success_max
                        new_size = success_max + int(window_diff / 2)
                    size = new_size
            results.append(
                [stream_id.value, success_max, failed_max, gate_size])
    write_results(results)


bench_stream_id()
# bench_stream_gate()
# write_results(results)

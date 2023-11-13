import subprocess
import logging
from tqdm import tqdm
import time

def test_connection():
    cmd = ["ssh", "h1", "hostname"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        assert result.returncode == 0
    except AssertionError:
        logging.critical("SSH connection to h1 could not be established!")
    logging.info("Connection established successfully")

def clean_up():
    cmd = ["ssh", "h1", "sudo pkill python3; sudo pkill tcpreplay; echo 'Senders killed'"]
    result = subprocess.run(cmd, capture_output=True, text=True)

def start_sender(frame_size: int, speed: int, packet_count):
    cmd = ["ssh", "h1", f"sudo python3 send.py -l {frame_size} -s {speed} -c {packet_count} &"]
    result = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logging.info("  Sender started")

def start_controller():
    cmd = ["python3", "controller.py"]
    result = subprocess.run(cmd, capture_output=True, text=True)

def analyze_and_plot():
    cmd = ["python3", "../util/data.py"]
    result = subprocess.run(cmd, capture_output=True, text=True)



logging.basicConfig(level=logging.INFO, datefmt='%d.%m.%Y %I:%M:%S', format='[%(levelname)s] %(asctime)s %(message)s')

N = 50
try:
    test_connection()
    clean_up()


    for i in tqdm(range(N)):
        logging.info(f"Starting run {i+1}/{N}")
        start_sender(1500, 1000, -1)
        start_controller()
        time.sleep(2)
        clean_up()
        time.sleep(1)
        analyze_and_plot()
        logging.info(f"Run {i}/{N} complete")
    clean_up()
except KeyboardInterrupt:
    clean_up()
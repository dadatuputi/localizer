import atexit
import logging
import queue
import threading
import time
from threading import Event

import RPi.GPIO as GPIO
from tqdm import trange

import localizer

GPIO.setwarnings(False)

module_logger = logging.getLogger('localizer.antenna')

class AntennaStepperThread(threading.Thread):
    # Default number of steps per radian
    steps_per_revolution = 400
    degrees_per_step = 360 / steps_per_revolution
    microsteps_per_step = 32
    degrees_per_microstep = degrees_per_step / microsteps_per_step

    def __init__(self, response_queue, event_flag, duration, degrees, bearing):

        # Set up thread
        super().__init__()

        module_logger.info("Starting Stepper Thread")

        self.daemon = True
        self._response_queue = response_queue
        self._event_flag = event_flag
        self._duration = duration
        self._degrees = degrees
        self._bearing = bearing
        self._seq_position = 0

        self.PUL_min = 21
        self.DIR_min = 20
        self.ENA_min = 16

        # Set up GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.PUL_min, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(self.DIR_min, GPIO.OUT)
        GPIO.setup(self.ENA_min, GPIO.OUT)

    def run(self):
        # Wait for commands in the queue
        module_logger.info("Executing Stepper Thread")

        degrees_per_microstep = AntennaStepperThread.degrees_per_microstep
        pulses = round(self._degrees / degrees_per_microstep)
        wait = self._duration/pulses
        wait_half = wait/2

        if pulses < 0:
            GPIO.output(self.DIR_min, GPIO.LOW)
            pulses = -pulses
        else:
            GPIO.output(self.DIR_min, GPIO.HIGH)
            pass

        GPIO.output(self.ENA_min, GPIO.HIGH)

        # Optimization https://wiki.python.org/moin/PythonSpeed/PerformanceTips
        now = time.time
        sleep = time.sleep
        output = GPIO.output

        # Wait for the synchronization flag
        module_logger.info("Waiting for synchronization flag")
        self._event_flag.wait()

        curr_loop = 0
        remaining = 0
        loop_start_time = time.time()

        # Step through each step
        for step in range(0, pulses):
            # Calculate remaining time for current loop
            curr_loop = step*wait + loop_start_time

            output(21, 1)

            # Wait for half the remaining available time in the loop
            remaining = (curr_loop-now())-wait_half
            if remaining > 0:
                sleep(remaining)

            output(21, 0)

            # Wait remaining loop time, if any
            remaining = curr_loop - now()
            if remaining > 0:
                sleep(remaining)

        loop_stop_time = time.time()
        loop_average_time = (time.time() - loop_start_time) / pulses

        module_logger.info("Rotated antenna {} degrees for {:.2f}s (expected {}s)"
                           .format(self._degrees, loop_stop_time-loop_start_time, self._duration))

        GPIO.output(self.ENA_min, GPIO.LOW)

        # Put results on queue
        self._response_queue.put((loop_start_time, loop_stop_time, wait, loop_average_time))


def reset(degrees):
    """
    Reset the antenna at a fixed speed

    :param degrees: degrees to rotate
    :type degrees: int
    :return: number of degrees rotated
    :rtype: int
    """

    # Rate to turn in revolutions / sec
    _reset_rate = 5
    _duration = _reset_rate * (degrees / 360)

    _response_queue = queue.Queue()
    _flag = Event()
    _thread = AntennaStepperThread(_response_queue,
                                   _flag,
                                   _duration,
                                   degrees,
                                   0)
    _thread.start()

    _flag.set()

    # Display timer
    for sec in trange(round(_duration), desc="Resetting antenna for {}s".format(_duration)
            .format((str(localizer.params.duration)))):
        time.sleep(sec)

    _thread.join()
    return degrees


@atexit.register
def cleanup():
    """
    Cleanup - ensure GPIO is cleaned up properly
    """

    module_logger.info("Cleaning up GPIO")
    GPIO.cleanup()

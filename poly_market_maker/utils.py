import logging
import math
import os
import random
import yaml
from logging import config


def setup_logging(
    log_path="logging.yaml",
    log_level=logging.INFO,
    env_key="LOGGING_CONFIG_FILE",
):
    """
    :param default_path:
    :param default_level:
    :param env_key:
    :return:
    """
    log_value = os.getenv(env_key, None)
    if log_value:
        log_path = log_value
    if os.path.exists(log_path):
        with open(log_path) as fh:
            config.dictConfig(yaml.safe_load(fh.read()))
        logging.getLogger(__name__).info("Logging configured with config file!")
    else:
        logging.basicConfig(
            format="%(asctime)-15s %(levelname)-4s %(threadName)s %(message)s",
            level=log_level,
        )
        logging.getLogger(__name__).info("Logging configured with default attributes!")
    # Suppress requests and web3 verbose logs
    logging.getLogger("requests").setLevel(logging.INFO)
    logging.getLogger("web3").setLevel(logging.INFO)

def math_round_down(f: float, sig_digits: int) -> float:
    str_f = str(f).split(".")
    if len(str_f) > 1 and len(str_f[1]) == sig_digits:
        # don't round values which are already the number of sig_digits
        return f
    return math.floor((f * (10**sig_digits))) / (10**sig_digits)


def math_round_up(f: float, sig_digits: int) -> float:
    str_f = str(f).split(".")
    if len(str_f) > 1 and len(str_f[1]) == sig_digits:
        # don't round values which are already the number of sig_digits
        return f
    return math.ceil((f * (10**sig_digits))) / (10**sig_digits)


def add_randomness(price: float, lower: float, upper: float) -> float:
    return math_round_down(price + random.uniform(lower, upper), 2)


def randomize_default_price(price: float) -> float:
    return add_randomness(price, -0.1, 0.1)

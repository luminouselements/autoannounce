#!/usr/bin/env python3

"""
Meshtastic Scheduled Announcer

Features:
- TCP connection
- YAML configuration
- Template token replacement
- State change detection
- Dry-run mode
- Custom user tokens
- Cron friendly
"""

import argparse
import json
import logging
import logging.handlers
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
import meshtastic.mesh_interface
import meshtastic.tcp_interface


CONFIG_FILE = "config.yaml"


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print message only, do not transmit"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Send even if state unchanged"
    )

    return parser.parse_args()


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_targets(config):
    meshtastic_config = config["meshtastic"]

    if "targets" not in meshtastic_config:
        return [
            {
                "host": meshtastic_config["host"],
                "channel_indices": [
                    meshtastic_config.get("channel_index", 0)
                ]
            }
        ], False

    configured_targets = meshtastic_config["targets"]

    if not isinstance(configured_targets, list) or not configured_targets:
        raise ValueError(
            "meshtastic.targets must be a non-empty list."
        )

    targets = []
    seen_hosts = set()

    for index, target in enumerate(configured_targets):
        if not isinstance(target, dict):
            raise ValueError(
                f"meshtastic.targets[{index}] must be a mapping."
            )

        host = target.get("host")
        channel_indices = target.get("channel_indices")

        if not isinstance(host, str) or not host.strip():
            raise ValueError(
                f"meshtastic.targets[{index}].host must be a non-empty string."
            )

        if host in seen_hosts:
            raise ValueError(
                f"Duplicate target host configured: {host}"
            )
        seen_hosts.add(host)

        if not isinstance(channel_indices, list) or not channel_indices:
            raise ValueError(
                f"meshtastic.targets[{index}].channel_indices "
                "must be a non-empty list."
            )

        for channel_index in channel_indices:
            if (
                isinstance(channel_index, bool)
                or not isinstance(channel_index, int)
                or channel_index < 0
            ):
                raise ValueError(
                    f"Invalid channel index for target {host}: "
                    f"{channel_index!r}"
                )

        if len(set(channel_indices)) != len(channel_indices):
            raise ValueError(
                f"Duplicate channel index configured for target {host}."
            )

        targets.append(
            {
                "host": host,
                "channel_indices": channel_indices
            }
        )

    return targets, True


def setup_logging(config):
    logfile = config["logging"]["file"]

    Path(logfile).parent.mkdir(
        parents=True,
        exist_ok=True
    )

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    handler = logging.handlers.RotatingFileHandler(
        logfile,
        maxBytes=5 * 1024 * 1024,
        backupCount=5
    )

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s"
    )

    handler.setFormatter(formatter)
    logger.addHandler(handler)


def load_state(state_file):
    path = Path(state_file)

    if not path.exists():
        return {}

    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state_file, state):

    state_path = Path(state_file)

    state_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def get_hop_stats(nodes):

    one_hop = 0
    two_hop = 0
    three_plus = 0

    for node in nodes.values():

        hops = node.get("hopsAway")

        if hops == 1:
            one_hop += 1
        elif hops == 2:
            two_hop += 1
        elif hops and hops >= 3:
            three_plus += 1

    return (
        one_hop,
        two_hop,
        three_plus
    )


def get_best_neighbor(nodes):

    best_neighbor = "N/A"
    best_snr = -999

    for node in nodes.values():

        if node.get("hopsAway") != 0:
            continue

        snr = node.get("snr")

        if snr is None:
            continue

        if snr > best_snr:

            best_snr = snr

            best_neighbor = (
                node.get("user", {})
                .get("shortName", "Unknown")
            )

    return best_neighbor, best_snr


def calc_average(nodes, field):

    values = []

    for node in nodes.values():

        value = node.get(field)

        if isinstance(value, (int, float)):
            values.append(value)

    if not values:
        return "N/A"

    return round(sum(values) / len(values), 1)


def get_latest_node(nodes):

    latest_name = "N/A"
    latest_time = 0

    for node in nodes.values():

        last_heard = node.get("lastHeard", 0)

        if last_heard > latest_time:

            latest_time = last_heard

            latest_name = (
                node.get("user", {})
                .get("shortName", "Unknown")
            )

    return latest_name


def get_metrics(interface, config):

    nodes = interface.nodes

    try:
        my_node = interface.getMyNodeInfo()
    except Exception:
        my_node = {}

    user = my_node.get("user", {})
    metrics = my_node.get("deviceMetrics", {})
    position = my_node.get("position", {})

    node_count = len(nodes)

    direct_count = sum(
        1
        for node in nodes.values()
        if node.get("hopsAway") == 0
    )

    one_hop, two_hop, three_plus = (
        get_hop_stats(nodes)
    )

    best_neighbor, best_snr = (
        get_best_neighbor(nodes)
    )

    lat = None
    lon = None

    if position:
        lat = position.get("latitudeI")
        lon = position.get("longitudeI")

    if lat and lon:
        latitude = round(lat / 1e7, 6)
        longitude = round(lon / 1e7, 6)

        pos_string = (
            f"{latitude}, {longitude}"
        )
    else:
        latitude = "N/A"
        longitude = "N/A"
        pos_string = "N/A"

    firmware = (
        user.get("firmwareVersion")
        or my_node.get("firmwareVersion")
        or "Unknown"
    )

    tokens = {
        "LONG_NAME":
            user.get("longName", "Unknown"),

        "SHORT_NAME":
            user.get("shortName", "UNK"),

        "NODE_COUNT":
            node_count,

        "DIRECT_COUNT":
            direct_count,

        "ONE_HOP_COUNT":
            one_hop,

        "TWO_HOP_COUNT":
            two_hop,

        "THREE_PLUS_HOP_COUNT":
            three_plus,

        "BATTERY":
            metrics.get(
                "batteryLevel",
                "N/A"
            ),

        "VOLTAGE":
            metrics.get(
                "voltage",
                "N/A"
            ),

        "CHANNEL_UTIL":
            round(
                metrics.get(
                    "channelUtilization",
                    0
                ),
                1
            ),

        "AIRTX":
            round(
                metrics.get(
                    "airUtilTx",
                    0
                ),
                1
            ),

        "TIME":
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "FIRMWARE":
            firmware,

        "HW_MODEL":
            user.get(
                "hwModel",
                "Unknown"
            ),

        "POSITION":
            pos_string,

        "LATITUDE":
            latitude,

        "LONGITUDE":
            longitude,

        "TOP_NEIGHBOR":
            best_neighbor,

        "BEST_SNR":
            (
                round(best_snr, 1)
                if best_snr != -999
                else "N/A"
            ),

        "AVERAGE_SNR":
            calc_average(
                nodes,
                "snr"
            ),

        "AVERAGE_RSSI":
            calc_average(
                nodes,
                "rssi"
            ),

        "LOCAL_NODE_ID":
            user.get("id", "N/A"),

        "LOCAL_NODE_NUM":
            my_node.get("num", "N/A"),

        "LAST_HEARD_NODE":
            get_latest_node(nodes),

        "LAST_HEARD_TIME":
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "GPS_LOCK":
            (
                "YES"
                if position else "NO"
            ),

        "ALTITUDE":
            position.get(
                "altitude",
                "N/A"
            ),

        "MQTT_STATUS":
            "N/A",

        "REGION":
            "N/A",

        "UPTIME":
            "N/A",

        "PRIMARY_CHANNEL":
            config["meshtastic"]
            .get(
                "channel_index",
                0
            ),

        "CHANNEL_NAME":
            f"Channel "
            f"{config['meshtastic'].get('channel_index',0)}",

        "WEATHER":
            "Disabled",

        "AIRTIME_WARNING":
            (
                "HIGH"
                if metrics.get(
                    "airUtilTx",
                    0
                ) > 10
                else "OK"
            ),

        "UTILIZATION_WARNING":
            (
                "HIGH"
                if metrics.get(
                    "channelUtilization",
                    0
                ) > 50
                else "OK"
            )
    }

    for key, value in config.get(
        "custom",
        {}
    ).items():
        tokens[key] = value

    return tokens


def render_template(template, tokens):

    result = template

    for key, value in tokens.items():

        result = result.replace(
            f"{{{key}}}",
            str(value)
        )

    return result


def validate_message_size(message):
    payload_size = len(message.encode("utf-8"))
    payload_limit = (
        meshtastic.mesh_interface
        .mesh_pb2.Constants.DATA_PAYLOAD_LEN
    )

    if payload_size > payload_limit:
        raise ValueError(
            f"Announcement is {payload_size} UTF-8 bytes; "
            f"Meshtastic allows at most {payload_limit}."
        )

    return payload_size, payload_limit


def state_snapshot(tokens):

    return {
        "NODE_COUNT":
            tokens["NODE_COUNT"],

        "DIRECT_COUNT":
            tokens["DIRECT_COUNT"],

        "BATTERY":
            tokens["BATTERY"],

        "TOP_NEIGHBOR":
            tokens["TOP_NEIGHBOR"],

        "BEST_SNR":
            tokens["BEST_SNR"]
    }


def print_dry_run(host, channel_indices, message):
    payload_size = len(message.encode("utf-8"))
    payload_limit = (
        meshtastic.mesh_interface
        .mesh_pb2.Constants.DATA_PAYLOAD_LEN
    )

    print(
        f"\n--- Generated Message for {host} "
        f"(channels {', '.join(map(str, channel_indices))}) ---\n"
    )
    print(message)
    print(
        f"\nPayload: {payload_size}/{payload_limit} UTF-8 bytes"
    )
    if payload_size > payload_limit:
        print(
            "WARNING: Message exceeds the "
            "Meshtastic payload limit."
        )
    print("\n-------------------------\n")


def main():

    args = parse_args()
    exit_code = 0

    try:

        config = load_config()

        setup_logging(config)

        targets, multiple_targets = get_targets(config)
        previous_state = load_state(config["state_file"])

        send_only_on_change = (
            config["announce"]
            .get(
                "send_only_on_change",
                True
            )
        )

        if args.dry_run:
            sys.stdout.reconfigure(
                encoding="utf-8",
                errors="backslashreplace"
            )

        if multiple_targets:
            if (
                not isinstance(previous_state, dict)
                or not isinstance(previous_state.get("targets"), dict)
            ):
                target_states = {}
            else:
                target_states = previous_state["targets"]
        else:
            target_states = {}

    except Exception:

        logging.exception(
            "Fatal error occurred"
        )
        return 1

    for target in targets:
        host = target["host"]
        channel_indices = target["channel_indices"]
        interface = None

        try:
            logging.info("Connecting to %s", host)
            interface = (
                meshtastic.tcp_interface
                .TCPInterface(host)
            )

            tokens = get_metrics(interface, config)
            current_state = state_snapshot(tokens)
            message = render_template(
                config["announce"]["template"],
                tokens
            )

            if multiple_targets:
                host_states = target_states.get(host, {})
                if not isinstance(host_states, dict):
                    host_states = {}
            else:
                host_states = {}

            if args.dry_run:
                if multiple_targets or (
                    not send_only_on_change
                    or current_state != previous_state
                    or args.force
                ):
                    print_dry_run(host, channel_indices, message)
                else:
                    logging.info(
                        "No change detected for %s.",
                        host
                    )
                time.sleep(2)
                continue

            sent_any = False

            for channel_index in channel_indices:
                if multiple_targets:
                    channel_state = host_states.get(
                        str(channel_index),
                        {}
                    )
                else:
                    channel_state = previous_state

                changed = current_state != channel_state

                if (
                    send_only_on_change
                    and not changed
                    and not args.force
                ):
                    logging.info(
                        "No change detected for %s channel %s.",
                        host,
                        channel_index
                    )
                    continue

                validate_message_size(message)
                interface.sendText(
                    message,
                    channelIndex=channel_index
                )
                time.sleep(2)
                sent_any = True

                if multiple_targets:
                    host_states[str(channel_index)] = current_state
                    target_states[host] = host_states
                    save_state(
                        config["state_file"],
                        {"targets": target_states}
                    )
                else:
                    save_state(
                        config["state_file"],
                        current_state
                    )

                logging.info(
                    "Announcement submitted to %s channel %s.",
                    host,
                    channel_index
                )

            if sent_any:
                logging.info(
                    "Announcement sent to %s.",
                    host
                )

        except Exception:
            logging.exception(
                "Failed to process target %s",
                host
            )
            exit_code = 1

        finally:
            if interface:
                try:
                    interface.close()
                except Exception:
                    logging.exception(
                        "Failed to close Meshtastic interface for %s",
                        host
                    )
                    exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
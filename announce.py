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
STALE_NODE_AFTER_SECONDS = 24 * 60 * 60
LOW_BATTERY_THRESHOLD = 20


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
        request_environment = meshtastic_config.get(
            "request_environment_metrics",
            False
        )
        if not isinstance(request_environment, bool):
            raise ValueError(
                "meshtastic.request_environment_metrics must be a boolean."
            )

        return [
            {
                "host": meshtastic_config["host"],
                "channel_indices": [
                    meshtastic_config.get("channel_index", 0)
                ],
                "request_environment_metrics": request_environment
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

        request_environment = target.get(
            "request_environment_metrics",
            False
        )
        if not isinstance(request_environment, bool):
            raise ValueError(
                f"meshtastic.targets[{index}]."
                "request_environment_metrics must be a boolean."
            )

        targets.append(
            {
                "host": host,
                "channel_indices": channel_indices,
                "request_environment_metrics": request_environment
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

        if (
            isinstance(last_heard, (int, float))
            and not isinstance(last_heard, bool)
            and last_heard > latest_time
        ):

            latest_time = last_heard

            latest_name = (
                (node.get("user") or {})
                .get("shortName", "Unknown")
            )

    return latest_name, latest_time


def get_mesh_activity(nodes, current_time):

    one_hour_cutoff = current_time - 3600
    one_day_cutoff = current_time - STALE_NODE_AFTER_SECONDS
    nodes_seen_1h = 0
    nodes_seen_24h = 0
    stale_node_count = 0

    for node in nodes.values():
        last_heard = node.get("lastHeard")
        if (
            isinstance(last_heard, bool)
            or not isinstance(last_heard, (int, float))
            or last_heard <= 0
        ):
            continue

        if last_heard > one_hour_cutoff:
            nodes_seen_1h += 1
        if last_heard > one_day_cutoff:
            nodes_seen_24h += 1
        else:
            stale_node_count += 1

    return nodes_seen_1h, nodes_seen_24h, stale_node_count


def format_age(age_seconds):

    age_seconds = max(0, int(age_seconds))

    if age_seconds < 60:
        return f"{age_seconds}s"

    days, remainder = divmod(age_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def get_numeric_metric(metrics, *keys):

    for key in keys:
        value = metrics.get(key)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            return round(value, 1)

    return "N/A"


def get_units(config):

    units = config.get("units", "metric")
    if not isinstance(units, str) or units.lower() not in {
        "metric",
        "imperial"
    }:
        raise ValueError("units must be either 'metric' or 'imperial'.")

    return units.lower()


def convert_metric(value, factor, offset=0, precision=1):

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "N/A"

    return round(value * factor + offset, precision)


def request_environment_metrics_if_missing(interface, channel_index):

    try:
        my_node = interface.getMyNodeInfo() or {}
    except Exception:
        logging.exception(
            "Unable to inspect node before requesting environment telemetry."
        )
        return

    environment_metrics = (
        my_node.get("environmentMetrics")
        or my_node.get("environment_metrics")
        or {}
    )
    if (
        get_numeric_metric(environment_metrics, "temperature") != "N/A"
        and get_numeric_metric(
            environment_metrics,
            "barometricPressure",
            "barometric_pressure"
        ) != "N/A"
    ):
        return

    node_num = my_node.get("num")
    if not isinstance(node_num, int) or isinstance(node_num, bool):
        logging.warning(
            "Cannot request environment telemetry: local node number is unavailable."
        )
        return

    try:
        logging.info(
            "Requesting environment telemetry from local node %s.",
            node_num
        )
        interface.sendTelemetry(
            destinationId=node_num,
            wantResponse=True,
            channelIndex=channel_index,
            telemetryType="environment_metrics"
        )
    except Exception:
        logging.exception(
            "Environment telemetry request failed; using cached values."
        )


def format_uptime(uptime_seconds):

    if uptime_seconds is None:
        return "N/A"

    if isinstance(uptime_seconds, bool) or not isinstance(
        uptime_seconds,
        int
    ):
        raise TypeError("Device uptime must be an integer number of seconds.")

    if uptime_seconds < 0:
        raise ValueError("Device uptime must not be negative.")

    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def get_metrics(interface, config):

    nodes = interface.nodes
    units = get_units(config)

    try:
        my_node = interface.getMyNodeInfo()
    except Exception:
        my_node = {}

    user = my_node.get("user") or {}
    metrics = my_node.get("deviceMetrics") or {}
    position = my_node.get("position") or {}
    environment_metrics = (
        my_node.get("environmentMetrics")
        or my_node.get("environment_metrics")
        or {}
    )

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

    if lat is not None and lon is not None:
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

    temperature = get_numeric_metric(
        environment_metrics,
        "temperature"
    )
    barometric_pressure = get_numeric_metric(
        environment_metrics,
        "barometricPressure",
        "barometric_pressure"
    )
    ground_speed = get_numeric_metric(
        position,
        "groundSpeed",
        "ground_speed"
    )
    altitude = get_numeric_metric(position, "altitude")
    if units == "imperial":
        if temperature != "N/A":
            temperature = convert_metric(temperature, 9 / 5, 32)
        if ground_speed != "N/A":
            ground_speed = convert_metric(ground_speed, 0.621371)
        if altitude != "N/A":
            altitude = convert_metric(altitude, 3.28084)

    current_time = time.time()
    latest_node, latest_heard = get_latest_node(nodes)
    nodes_seen_1h, nodes_seen_24h, stale_node_count = (
        get_mesh_activity(nodes, current_time)
    )
    low_battery_count = 0
    for node in nodes.values():
        node_metrics = node.get("deviceMetrics") or {}
        battery_level = node_metrics.get("batteryLevel")
        if (
            isinstance(battery_level, (int, float))
            and not isinstance(battery_level, bool)
            and 0 <= battery_level <= LOW_BATTERY_THRESHOLD
        ):
            low_battery_count += 1

    configured_channel = config["meshtastic"].get("channel_index", 0)

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

        "NODES_SEEN_1H":
            nodes_seen_1h,

        "NODES_SEEN_24H":
            nodes_seen_24h,

        "STALE_NODE_COUNT":
            stale_node_count,

        "LOW_BATTERY_COUNT":
            low_battery_count,

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

        "UPTIME":
            format_uptime(
                metrics.get("uptimeSeconds")
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
            latest_node,

        "LAST_HEARD_TIME":
            (
                datetime.fromtimestamp(latest_heard).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                if latest_heard
                else "N/A"
            ),

        "LAST_HEARD_AGE":
            (
                format_age(current_time - latest_heard)
                if latest_heard
                else "N/A"
            ),

        "GPS_LOCK":
            (
                "YES"
                if lat is not None and lon is not None
                else "NO"
            ),

        "GPS_SATELLITES":
            position.get("satsInView", "N/A"),

        "GROUND_SPEED":
            ground_speed,

        "ALTITUDE":
            altitude,

        "TEMPERATURE":
            temperature,

        "RELATIVE_HUMIDITY":
            get_numeric_metric(
                environment_metrics,
                "relativeHumidity",
                "relative_humidity"
            ),

        "BAROMETRIC_PRESSURE":
            barometric_pressure,

        "MQTT_STATUS":
            "N/A",

        "REGION":
            "N/A",

        "PRIMARY_CHANNEL":
            configured_channel,

        "CHANNEL_NAME":
            f"Channel {configured_channel}",

        "CHANNEL_INDEX":
            configured_channel,

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


def channel_tokens(tokens, channel_index):

    result = dict(tokens)
    result["CHANNEL_INDEX"] = channel_index
    result["PRIMARY_CHANNEL"] = channel_index
    result["CHANNEL_NAME"] = f"Channel {channel_index}"
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
            tokens["BEST_SNR"],

        "NODES_SEEN_1H":
            tokens["NODES_SEEN_1H"],

        "NODES_SEEN_24H":
            tokens["NODES_SEEN_24H"],

        "STALE_NODE_COUNT":
            tokens["STALE_NODE_COUNT"],

        "LOW_BATTERY_COUNT":
            tokens["LOW_BATTERY_COUNT"],

        "LAST_HEARD_NODE":
            tokens["LAST_HEARD_NODE"],

        "LAST_HEARD_TIME":
            tokens["LAST_HEARD_TIME"],

        "GPS_SATELLITES":
            tokens["GPS_SATELLITES"],

        "GROUND_SPEED":
            tokens["GROUND_SPEED"],

        "TEMPERATURE":
            tokens["TEMPERATURE"],

        "RELATIVE_HUMIDITY":
            tokens["RELATIVE_HUMIDITY"],

        "BAROMETRIC_PRESSURE":
            tokens["BAROMETRIC_PRESSURE"]
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

            if (
                target["request_environment_metrics"]
                and not args.dry_run
            ):
                request_environment_metrics_if_missing(
                    interface,
                    channel_indices[0]
                )

            tokens = get_metrics(interface, config)
            current_state = state_snapshot(tokens)
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
                    for channel_index in channel_indices:
                        message = render_template(
                            config["announce"]["template"],
                            channel_tokens(tokens, channel_index)
                        )
                        print_dry_run(
                            host,
                            [channel_index],
                            message
                        )
                else:
                    logging.info(
                        "No change detected for %s.",
                        host
                    )
                time.sleep(3)
                continue

            sent_any = False

            for channel_index in channel_indices:
                message = render_template(
                    config["announce"]["template"],
                    channel_tokens(tokens, channel_index)
                )

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
                time.sleep(3)
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
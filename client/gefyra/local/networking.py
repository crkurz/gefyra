import logging

from docker.errors import NotFound, APIError
from docker.models.networks import Network
from docker.types import IPAMConfig, IPAMPool

from gefyra.configuration import ClientConfiguration
from gefyra.local import CREATED_BY_LABEL

logger = logging.getLogger(__name__)


def create_gefyra_network(config: ClientConfiguration, suffix: str = "") -> Network:
    gefyra_network = handle_create_network(config, suffix)
    logger.debug(f"Network {gefyra_network.attrs}")
    return gefyra_network


def handle_create_network(config: ClientConfiguration, suffix: str = "") -> Network:
    DOCKER_MTU_OPTION = "com.docker.network.driver.mtu"
    network_name = f"{config.NETWORK_NAME}-{suffix}"
    try:
        network = config.DOCKER.networks.get(network_name)
        logger.info("Gefyra network already exists")
        if (
            CREATED_BY_LABEL[0] not in network.attrs["Labels"]
            or network.attrs["Labels"][CREATED_BY_LABEL[0]] != "true"
        ):
            logger.debug(f"Docker network '{network.name}' is not managed by Gefyra")
        if (
            "Options" in network.attrs
            and DOCKER_MTU_OPTION in network.attrs["Options"]
            and network.attrs["Options"][DOCKER_MTU_OPTION] != config.WIREGUARD_MTU
        ) or (
            "Options" in network.attrs
            and DOCKER_MTU_OPTION not in network.attrs["Options"]
        ):
            _mtu = (
                network.attrs["Options"].get(DOCKER_MTU_OPTION)
                if "Options" in network.attrs
                else "default"
            )
            logger.warning(
                f"The MTU value of the '{network_name}' network (={_mtu}) is different from the --wireguard-mtu parameter "
                f"(={config.WIREGUARD_MTU}) or default. You may experience bad network connections. Consider removing "
                f"the network '{network_name}' with 'docker network rm gefyra' before running 'gefyra up'."
            )
        return network
    except NotFound:
        pass

    # this is a workaround to select a free subnet (instead of finding it with python code)
    temp_network = config.DOCKER.networks.create(network_name, driver="bridge")
    subnet = temp_network.attrs["IPAM"]["Config"][0]["Subnet"]
    temp_network.remove()  # remove the temp network again

    ipam_pool = IPAMPool(subnet=f"{subnet}", aux_addresses={})
    ipam_config = IPAMConfig(pool_configs=[ipam_pool])
    network = config.DOCKER.networks.create(
        network_name,
        driver="bridge",
        ipam=ipam_config,
        labels={
            CREATED_BY_LABEL[0]: CREATED_BY_LABEL[1],
        },
        options={DOCKER_MTU_OPTION: config.WIREGUARD_MTU},
    )
    logger.info(f"Created network '{network_name}' ({network.short_id})")
    return network


def handle_remove_network(config: ClientConfiguration, suffix: str = "") -> None:
    """Removes all docker networks with the given name."""
    # we would need the id to identify the network unambiguously, so we just remove all networks that can be found with
    # the given name, under the assumption that no other docker network inadvertently uses the same name
    try:
        gefyra_network = config.DOCKER.networks.get(f"{config.NETWORK_NAME}{suffix}")
        if (
            CREATED_BY_LABEL[0] in gefyra_network.attrs["Labels"]
            and gefyra_network.attrs["Labels"][CREATED_BY_LABEL[0]] == "true"
        ):
            logger.info(f"Removing Docker network {gefyra_network.name}")
            gefyra_network.remove()
        else:
            logger.info(
                f"Docker network {gefyra_network.name} is not managed by Gefyra"
            )
    except NotFound:
        pass
    except APIError as e:
        logger.error(f"Could not remove network due to the following error: {e}")


def kill_remainder_container_in_network(
    config: ClientConfiguration, network_name
) -> None:
    """Kills all containers from this network"""
    try:
        network = config.DOCKER.networks.get(network_name)
        containers = network.attrs["Containers"].keys()
        for container in containers:
            c = config.DOCKER.containers.get(container)
            if (
                CREATED_BY_LABEL[0] in c.attrs["Config"]["Labels"]
                and c.attrs["Config"]["Labels"][CREATED_BY_LABEL[0]] == "true"
            ):
                c.kill()
    except NotFound:
        pass

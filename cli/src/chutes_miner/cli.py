import json
import asyncio
import aiohttp
import typer
from rich.console import Console
from rich.table import Table
from rich import box
import datetime
from chutes_miner.util import sign_request

app = typer.Typer(no_args_is_help=True)


def format_memory(memory_bytes):
    """
    Convert memory from bytes to GB and format nicely.
    """
    return f"{memory_bytes / (1024**3):.1f}GB"


def format_date(date_str):
    """
    Format datetime string to a more readable format.
    """
    dt = datetime.datetime.fromisoformat(date_str)
    return dt.strftime("%Y-%m-%d %H:%M")


def format_verification(error, verified_at):
    """
    Helper to format table cell for GPU verification.
    """
    if verified_at:
        return f"[green]Verified: {format_date(verified_at)}[/green]"
    elif error:
        return f"[red]Error: {error}[/red]"
    return "[yellow]Pending[/yellow]"


def display_local_inventory(inventory):
    """
    Render inventory in fancy tables.
    """
    console = Console()
    for server in inventory:
        server_table = Table(title=f"Server: {server['name']}", box=box.ROUNDED)
        server_table.add_column("Property", style="cyan")
        server_table.add_column("Value")
        server_table.add_row("Status", server["status"])
        server_table.add_row("GPUs", str(server["gpu_count"]))
        server_table.add_row("Memory/GPU", f"{server['memory_per_gpu']}GB")
        server_table.add_row("CPU/GPU", str(server["cpu_per_gpu"]))
        server_table.add_row("Hourly Cost", f"${server['hourly_cost']:.2f}")
        server_table.add_row("IP Address", server["ip_address"])
        server_table.add_row("Created", format_date(server["created_at"]))
        console.print(server_table)
        console.print()

        # Deployments.
        if server["deployments"]:
            deploy_table = Table(title="Active Deployments", box=box.ROUNDED)
            deploy_table.add_column("Model Name")
            deploy_table.add_column("GPUs")
            deploy_table.add_column("Port")
            deploy_table.add_column("Created")
            deploy_table.add_column("Status")
            for deploy in server["deployments"]:
                status_text = (
                    "[green]Active[/green]"
                    if deploy["active"] and not deploy["stub"]
                    else "[red]Inactive[/red]"
                )
                deploy_table.add_row(
                    deploy["chute"]["name"],
                    str(len(deploy["gpus"])),
                    str(deploy["port"]),
                    format_date(deploy["created_at"]),
                    status_text,
                )
            console.print(deploy_table)
            console.print()

        # GPU details.
        gpu_table = Table(title="GPU Details", box=box.ROUNDED)
        gpu_table.add_column("Name")
        gpu_table.add_column("Memory")
        gpu_table.add_column("Clock (MHz)")
        gpu_table.add_column("Processors")
        gpu_table.add_column("Status")
        for gpu in server["gpus"]:
            status_text = "[green]Verified[/green]" if gpu["verified"] else "[red]Unverified[/red]"
            gpu_table.add_row(
                gpu["device_info"]["name"],
                format_memory(gpu["device_info"]["memory"]),
                str(int(gpu["device_info"]["clock_rate"] / 1000)),
                str(gpu["device_info"]["processors"]),
                status_text,
            )

        console.print(gpu_table)
        console.print("\n" + "=" * 80 + "\n")


def display_remote_inventory(inventory):
    """
    Render remote/validator inventory.
    """
    console = Console()
    table = Table(title="GPU Information")
    table.add_column("Name", style="cyan")
    table.add_column("Chute", style="cyan")
    table.add_column("Memory (GB)", justify="right", style="green")
    table.add_column("Clock (MHz)", justify="right", style="red")
    table.add_column("Created At", style="blue")
    table.add_column("GPU Verification", style="white")
    table.add_column("Instance verification", style="white")
    for gpu in inventory:
        table.add_row(
            gpu["name"],
            f"{gpu['chute_id']} {gpu['chute']}",
            format_memory(gpu["memory"]),
            f"{gpu['clock_rate'] / 1000:.0f}",
            format_date(gpu["created_at"]),
            format_verification(gpu["verification_error"], gpu["verified_at"]),
            format_verification(gpu["inst_verification_error"], gpu["inst_verified_at"]),
        )
    console.print(table)
    console.print("\n" + "=" * 80 + "\n")


def local_inventory(
    raw_json: bool = typer.Option(False, help="Display raw JSON output"),
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    miner_api: str = typer.Option("http://127.0.0.1:32000", help="Miner API base URL"),
):
    """
    Show local inventory.
    """

    async def _local_inventory():
        nonlocal hotkey, miner_api, raw_json
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            headers, _ = sign_request(hotkey, purpose="management")
            async with session.get(
                f"{miner_api.rstrip('/')}/servers/",
                headers=headers,
                timeout=30,
            ) as resp:
                inventory = await resp.json()
                if raw_json:
                    print(json.dumps(inventory, indent=2))
                else:
                    display_local_inventory(inventory)

    asyncio.run(_local_inventory())


def remote_inventory(
    raw_json: bool = typer.Option(False, help="Display raw JSON output"),
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    validator_api: str = typer.Option("https://api.chutes.ai", help="Validator API base URL"),
):
    """
    Show remote (i.e., what the validator has tracked) inventory.
    """

    async def _remote_inventory():
        nonlocal hotkey, validator_api, raw_json
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            headers, _ = sign_request(hotkey, purpose="miner", remote=True)
            inventory = []
            gpu_map = {}
            async with session.get(f"{validator_api}/miner/nodes/", headers=headers) as resp:
                async for content_enc in resp.content:
                    content = content_enc.decode()
                    if content.startswith("data: "):
                        inventory.append(json.loads(content[6:]))
                        gpu_map[inventory[-1]["uuid"]] = inventory[-1]
                        gpu_map[inventory[-1]["uuid"]].update(
                            {
                                "chute": None,
                                "chute_id": None,
                                "inst_verification_error": None,
                                "inst_verified_at": None,
                            }
                        )
            async with session.get(f"{validator_api}/miner/inventory", headers=headers) as resp:
                for item in await resp.json():
                    if item["gpu_id"] in gpu_map:
                        gpu_map[item["gpu_id"]].update(
                            {
                                "chute": item["chute_name"],
                                "chute_id": item["chute_id"],
                                "inst_verification_error": item["verification_error"],
                                "inst_verified_at": item["last_verified_at"],
                            }
                        )
            inventory = sorted(inventory, key=lambda o: o["created_at"])
            if raw_json:
                print(json.dumps(inventory, indent=2))
            else:
                display_remote_inventory(inventory)

    asyncio.run(_remote_inventory())


def add_node(
    name: str = typer.Option(..., help="Name of the server/node"),
    validator: str = typer.Option(..., help="Validator ss58 this node is allocated to"),
    hourly_cost: float = typer.Option(..., help="Hourly cost, used in optimizing autoscaling"),
    gpu_short_ref: str = typer.Option(..., help="GPU short reference"),
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    miner_api: str = typer.Option("http://127.0.0.1:32000", help="Miner API base URL"),
):
    """
    Entrypoint for adding a new kubernetes node.
    """

    async def _add_node():
        nonlocal name, validator, hourly_cost, gpu_short_ref, hotkey, miner_api
        async with aiohttp.ClientSession(raise_for_status=False) as session:
            payload = {
                "name": name,
                "validator": validator,
                "hourly_cost": hourly_cost,
                "gpu_short_ref": gpu_short_ref,
            }
            headers, payload_string = sign_request(hotkey, payload=payload)
            async with session.post(
                f"{miner_api.rstrip('/')}/servers/",
                headers=headers,
                data=payload_string,
                timeout=900,
            ) as resp:
                if resp.status != 200:
                    print(f"\033[31mError adding node:\n{await resp.text()}\033[0m")
                    resp.raise_for_status()
                async for content in resp.content:
                    if content.strip():
                        payload = json.loads(content.decode()[6:])
                        print(f"\033[34m{payload['timestamp']}\033[0m {payload['message']}")

    asyncio.run(_add_node())


def delete_node(
    name: str = typer.Option(..., help="Name of the server/node"),
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    miner_api: str = typer.Option("http://127.0.0.1:32000", help="Miner API base URL"),
):
    """
    Entrypoint for deleting a kubernetes node.
    """

    async def _delete_node():
        nonlocal name, hotkey, miner_api
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            headers, payload_string = sign_request(hotkey, purpose="management")
            async with session.delete(
                f"{miner_api.rstrip('/')}/servers/{name}",
                headers=headers,
            ) as resp:
                print(json.dumps(await resp.json(), indent=2))

    asyncio.run(_delete_node())


def purge_deployments(
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    miner_api: str = typer.Option("http://127.0.0.1:32000", help="Miner API base URL"),
):
    """
    Rebalance all chutes - this just deletes all current instances and let's gepetto re-scale for max $$$
    """

    async def _purge_deployments():
        nonlocal hotkey, miner_api
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            headers, payload_string = sign_request(hotkey, purpose="management")
            async with session.delete(
                f"{miner_api.rstrip('/')}/deployments/purge",
                headers=headers,
            ) as resp:
                print(json.dumps(await resp.json(), indent=2))

    asyncio.run(_purge_deployments())

def purge_node(
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    miner_api: str = typer.Option("http://127.0.0.1:32000", help="Miner API base URL"),
    name: str = typer.Option(..., help="Name or ID of the server/node"),
):
    """
    Purge chutes deployed to specified server/node
    """

    async def _purge_node_deployment():
        nonlocal hotkey, miner_api, name
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            headers, payload_string = sign_request(hotkey, purpose="management")
            async with session.delete(
                f"{miner_api.rstrip('/')}/deployments/purge/node/{name}",
                headers=headers,
            ) as resp:
                print(json.dumps(await resp.json(), indent=2))

    asyncio.run(_purge_node_deployment())

def purge_deployment(
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    miner_api: str = typer.Option("http://127.0.0.1:32000", help="Miner API base URL"),
    deployment_id: str = typer.Option(..., help="ID of the deployment"),
):
    """
    Purge specific chutes deployed to a node
    """

    async def _purge_deployment():
        nonlocal hotkey, miner_api, deployment_id
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            headers, payload_string = sign_request(hotkey, purpose="management")
            async with session.delete(
                f"{miner_api.rstrip('/')}/deployments/purge/deployment/{deployment_id}",
                headers=headers,
            ) as resp:
                print(json.dumps(await resp.json(), indent=2))

    asyncio.run(_purge_deployment())

def scorch_remote(
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    validator_api: str = typer.Option("https://api.chutes.ai", help="Validator API base URL"),
):
    """
    Purge all inventory from the validator API.
    """

    async def _scorch_remote():
        nonlocal hotkey, validator_api
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            headers, _ = sign_request(hotkey, purpose="miner", remote=True)
            async with session.get(
                f"{validator_api.rstrip('/')}/miner/nodes/",
                headers=headers,
            ) as resp:
                async for line in resp.content:
                    if not line or not line.startswith(b"data:"):
                        continue
                    gpu = json.loads(line.decode()[6:])
                    print(f"Deleting {gpu['name']} with uuid {gpu['uuid']}")
                    headers, _ = sign_request(hotkey, purpose="nodes", remote=True)
                    async with session.delete(
                        f"{validator_api.rstrip('/')}/nodes/{gpu['uuid']}",
                        headers=headers,
                    ) as resp:
                        print(f"  successfully deleted {gpu['name']} with uuid {gpu['uuid']}")

    asyncio.run(_scorch_remote())


def delete_remote(
    gpu_id: str = typer.Option(help="GPU UUID to delete, aka node_node on validator side"),
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    validator_api: str = typer.Option("https://api.chutes.ai", help="Validator API base URL"),
):
    """
    Delete a single GPU from validator.
    """

    async def _delete_remote():
        nonlocal hotkey, validator_api, gpu_id
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            headers, _ = sign_request(hotkey, purpose="nodes", remote=True)
            async with session.delete(
                f"{validator_api.rstrip('/')}/nodes/{gpu_id}",
                headers=headers,
            ) as _:
                print(f"  successfully deleted {gpu_id}")

    asyncio.run(_delete_remote())


async def _lock_or_unlock_server(lock: bool, name: str, hotkey: str, miner_api: str):
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        headers, _ = sign_request(hotkey, purpose="management")
        path = "/lock" if lock else "/unlock"
        async with session.get(
            f"{miner_api.rstrip('/')}/servers/{name}{path}",
            headers=headers,
        ) as resp:
            server = await resp.json()
            print(f"Server {server['name']} lock status is now: {server['locked']}")


def lock_server(
    name: str = typer.Option(..., help="Name of the server/node"),
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    miner_api: str = typer.Option("http://127.0.0.1:32000", help="Miner API base URL"),
):
    """
    Lock a server's deployments.
    """

    async def _lock_server():
        nonlocal name, hotkey, miner_api
        await _lock_or_unlock_server(lock=True, name=name, hotkey=hotkey, miner_api=miner_api)

    asyncio.run(_lock_server())


def unlock_server(
    name: str = typer.Option(..., help="Name of the server/node"),
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    miner_api: str = typer.Option("http://127.0.0.1:32000", help="Miner API base URL"),
):
    """
    Unlock a server's deployments.
    """

    async def _unlock_server():
        nonlocal name, hotkey, miner_api
        await _lock_or_unlock_server(lock=False, name=name, hotkey=hotkey, miner_api=miner_api)

    asyncio.run(_unlock_server())


app.command(name="add-node", help="Add a new kubernetes node to your cluster")(add_node)
app.command(name="delete-node", help="Delete a kubernetes node from your cluster")(delete_node)
app.command(
    name="purge-deployments", help="Purge all deployments, allowing autoscale from scratch"
)(purge_deployments)
app.command(
    name="purge-node", help="Purge all deployments from a given node, allowing autoscale from scratch"
)(purge_node)
app.command(
    name="purge-deployment", help="Purge single deployment, allowing autoscale from scratch"
)(purge_deployment)
app.command(name="local-inventory", help="Show local inventory")(local_inventory)
app.command(name="remote-inventory", help="Show remote inventory")(remote_inventory)
app.command(name="scorch-remote", help="Purge all GPUs/instances/etc. from validator")(
    scorch_remote
)
app.command(name="delete-remote", help="Remove a single GPU from validator inventory")(
    delete_remote
)
app.command(name="lock", help="Lock a server's deployments")(lock_server)
app.command(name="unlock", help="Unlock a server's deployments")(unlock_server)


if __name__ == "__main__":
    app()

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


def format_gpu_verification(error, verified_at):
    """
    Helper to format table cell for GPU verification.
    """
    if error:
        return f"[red]Error: {error}[/red]"
    elif verified_at:
        return f"[green]Verified: {format_date(verified_at)}[/green]"
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
            deploy_table.add_column("Chute ID")
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
                    deploy["chute"]["chute_id"],
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
    table.add_column("Memory (GB)", justify="right", style="green")
    table.add_column("Compute Cap.", justify="center", style="magenta")
    table.add_column("Processors", justify="right", style="yellow")
    table.add_column("Clock (MHz)", justify="right", style="red")
    table.add_column("Created At", style="blue")
    table.add_column("Verification Status", style="white")
    for gpu in inventory:
        table.add_row(
            gpu["name"],
            format_memory(gpu["memory"]),
            f"{gpu['major']}.{gpu['minor']}",
            str(gpu["processors"]),
            f"{gpu['clock_rate']/1000:.0f}",
            format_date(gpu["created_at"]),
            format_gpu_verification(gpu["verification_error"], gpu["verified_at"]),
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
    miner_api: str = typer.Option("http://127.0.0.1:32000", help="Miner API base URL"),
):
    """
    Show remote (i.e., what the validator has tracked) inventory.
    """

    async def _remote_inventory():
        nonlocal hotkey, miner_api, raw_json
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            headers, _ = sign_request(hotkey, purpose="miner", remote=True)
            inventory = []
            async with session.get("https://api.chutes.ai/miner/nodes/", headers=headers) as resp:
                async for content_enc in resp.content:
                    content = content_enc.decode()
                    if content.startswith("data: "):
                        inventory.append(json.loads(content[6:]))
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


app.command(name="add-node", help="Add a new kubernetes node to your cluster")(add_node)
app.command(name="delete-node", help="Delete a kubernetes node from your cluster")(delete_node)
app.command(
    name="purge-deployments", help="Purge all deployments, allowing autoscale from scratch"
)(purge_deployments)
app.command(name="local-inventory", help="Show local inventory")(local_inventory)
app.command(name="remote-inventory", help="Show remote inventory")(remote_inventory)


if __name__ == "__main__":
    app()

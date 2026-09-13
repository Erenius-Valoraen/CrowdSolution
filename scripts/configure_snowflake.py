"""One-step Snowflake config for CrowdSolution.
Asks for account, username, and token (token input is hidden), writes
~/.snowflake/connections.toml, then runs the connection smoke test."""
import getpass
import pathlib
import subprocess
import sys

cfg_dir = pathlib.Path.home() / ".snowflake"
cfg = cfg_dir / "connections.toml"
here = pathlib.Path(__file__).parent

print("Values come from the last result of snowflake_setup.sql.\n")
account = input("Account identifier (looks like ORGNAME-ACCOUNTNAME): ").strip()
user = input("Username: ").strip()
token = getpass.getpass("Token secret (hidden, just paste and press Enter): ").strip()
if not (account and user and token):
    sys.exit("All three values are required. Nothing was written.")

cfg_dir.mkdir(exist_ok=True)
cfg.write_text(
    "[crowdsolution]\n"
    f'account = "{account}"\n'
    f'user = "{user}"\n'
    'authenticator = "PROGRAMMATIC_ACCESS_TOKEN"\n'
    f'token = "{token}"\n'
    'role = "SYSADMIN"\n'
    'warehouse = "COMPUTE_WH"\n'
    'database = "SNOWFLAKE_PUBLIC_DATA_FREE"\n'
    'schema = "PUBLIC_DATA_FREE"\n',
    encoding="utf-8",
)
print(f"\nSaved {cfg}\nTesting connection...\n")
sys.exit(subprocess.call([sys.executable, str(here / "check_connection.py")]))

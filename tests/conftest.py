"""Make the scanner modules importable from the tests."""
import sys
from pathlib import Path

SCANNER = Path(__file__).resolve().parents[1] / "scanner"
if str(SCANNER) not in sys.path:
    sys.path.insert(0, str(SCANNER))


def field(api_name, label=None, type_="Text", description="", object_name="Acct__c"):
    """Terse Field factory for rule tests."""
    from orgiq_spike import Field
    return Field(object_name=object_name, api_name=api_name,
                 label=label if label is not None else api_name.replace("__c", "").replace("_", " "),
                 type=type_, description=description, help_text="", path="")

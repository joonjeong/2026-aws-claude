#!/usr/bin/env python3
"""CDK app entry point. Synth: `npx aws-cdk@latest synth` (no credentials needed)."""
import aws_cdk as cdk

from hub_stack import HubStack

app = cdk.App()
HubStack(app, "HubStack")
app.synth()

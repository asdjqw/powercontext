# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = (Path(__file__).parents[1] / ".github" / "workflows" / "e2e-harness.yml").read_text(encoding="utf-8")


def test_supplied_scope_keeps_acceptance_runnable_after_the_detector_is_skipped() -> None:
    jobs = yaml.safe_load(WORKFLOW)["jobs"]
    assert jobs["changes"]["if"] == "${{ inputs.suites == '' }}"
    assert "!cancelled()" in jobs["validate"]["if"]
    assert jobs["acceptance"]["needs"] == "validate"
    # A successful validate job does not clear the skipped ancestor for Actions'
    # implicit success(). Acceptance needs its own status function and success gate.
    assert jobs["acceptance"]["if"] == "${{ !cancelled() && needs.validate.result == 'success' }}"
    assert set(jobs["acceptance"]["strategy"]["matrix"]["database"]) == {"sqlite", "oceanbase"}


def test_e2e_scan_keeps_raw_scanner_output_out_of_artifacts() -> None:
    steps = yaml.safe_load(WORKFLOW)["jobs"]["acceptance"]["steps"]
    diagnostics = next(
        step for step in steps if step.get("with", {}).get("name", "").startswith("e2e-acceptance-diagnostics-")
    )
    assert diagnostics["with"]["path"] == (
        "${{ runner.temp }}/powercontext-e2e-diagnostics-${{ matrix.database }}/summary.txt"
    )


def test_e2e_diagnostics_upload_only_runs_for_failed_validation_or_scan() -> None:
    assert "steps.evidence_scan.outcome != 'success'" in WORKFLOW
    assert "steps.acceptance_scenarios.outcome != 'success'" in WORKFLOW


@pytest.mark.parametrize(
    ("proxy_settings", "expected"),
    [
        ({}, ""),
        ({"HTTPS_PROXY": "http://runner.invalid:7890"}, "http://runner.invalid:7890"),
        ({"HTTP_PROXY": "http://runner.invalid:7890"}, "http://runner.invalid:7890"),
        ({"https_proxy": "http://runner.invalid:7890"}, "http://runner.invalid:7890"),
        ({"http_proxy": "http://runner.invalid:7890"}, "http://runner.invalid:7890"),
        (
            {
                "POWERCONTEXT_E2E_AGENT_PROXY_URL": "http://user:secret@task-proxy.invalid:3128",
                "HTTPS_PROXY": "http://runner.invalid:7890",
            },
            "http://user:secret@task-proxy.invalid:3128",
        ),
    ],
)
def test_acceptance_passes_the_outbound_proxy_to_the_harness_without_printing_it(
    tmp_path: Path, proxy_settings: dict[str, str], expected: str
) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to execute the acceptance workflow step")
    steps = yaml.safe_load(WORKFLOW)["jobs"]["acceptance"]["steps"]
    command = next(step["run"] for step in steps if step.get("id") == "acceptance_scenarios")
    make = tmp_path / "make"
    make.write_text(
        '#!/bin/sh\nset -eu\n[ "$*" = harness-compose-acceptance ]\n'
        'printf %s "$POWERCONTEXT_E2E_AGENT_PROXY_URL" > "$PROXY_RESULT"\n',
        encoding="utf-8",
    )
    make.chmod(0o755)
    result_path = tmp_path / "proxy.txt"
    env = {key: value for key, value in os.environ.items() if "proxy" not in key.lower()}
    env.update(proxy_settings)
    env["PROXY_RESULT"] = result_path.name
    # Bash resolves its working directory and PATH syntax on both POSIX and Git Bash.
    command = 'export PATH="$PWD:$PATH"\n' + command

    result = subprocess.run(
        [bash, "-e", "-c", command], cwd=tmp_path, env=env, capture_output=True, text=True, check=True
    )

    assert result_path.read_text(encoding="utf-8") == expected
    assert not result.stdout
    assert not result.stderr

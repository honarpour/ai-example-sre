from __future__ import annotations

from app.fixtures.scenarios.bad_deploy import SCENARIO as BAD_DEPLOY
from app.fixtures.scenarios.config_flag import SCENARIO as CONFIG_FLAG
from app.fixtures.scenarios.downstream_dependency import SCENARIO as DOWNSTREAM_DEPENDENCY
from app.fixtures.scenarios.resource_leak import SCENARIO as RESOURCE_LEAK
from app.fixtures.scenarios.spec import Scenario

SCENARIOS: dict[str, Scenario] = {
    s.key: s for s in [BAD_DEPLOY, DOWNSTREAM_DEPENDENCY, RESOURCE_LEAK, CONFIG_FLAG]
}


def get_scenario(key: str) -> Scenario:
    try:
        return SCENARIOS[key]
    except KeyError as e:
        raise ValueError(
            f"Unknown scenario '{key}'. Known scenarios: {sorted(SCENARIOS)}"
        ) from e

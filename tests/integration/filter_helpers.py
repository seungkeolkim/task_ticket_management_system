"""테스트에서 실제 v2 조건과 URL을 읽기 쉽게 작성하는 도우미다."""

import json
from urllib.parse import urlencode


def filter_condition(field_name, operator, *values, negated=False):
    """고정값을 사용하는 v2 조건 하나를 구성한다."""
    return {
        "kind": "condition",
        "field": field_name,
        "operator": operator,
        "values": list(values),
        "negated": negated,
    }


def filter_definition(*conditions, logical_operator="AND", negated=False, **settings):
    """중첩 조건과 조회 설정으로 저장 가능한 v2 정의를 구성한다."""
    return {
        "schema_version": 2,
        "expression": {
            "kind": "group",
            "operator": logical_operator,
            "children": list(conditions),
            "negated": negated,
        },
        **settings,
    }


def filter_url(path, *conditions, page=None, **settings):
    """조건 트리 전체를 단일 filter query로 전달하는 URL을 구성한다."""
    parameters = {"filter": json.dumps(filter_definition(*conditions, **settings))}
    if page is not None:
        parameters["page"] = page
    return path + "?" + urlencode(parameters)

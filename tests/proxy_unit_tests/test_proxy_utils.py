import asyncio
import os
import sys
from unittest.mock import Mock
from litellm.proxy.utils import _get_redoc_url, _get_docs_url

import pytest
from fastapi import Request

sys.path.insert(
    0, os.path.abspath("../..")
)  # Adds the parent directory to the system path
import litellm
from unittest.mock import MagicMock, patch, AsyncMock

from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.auth_utils import is_request_body_safe
from litellm.proxy.litellm_pre_call_utils import (
    _get_dynamic_logging_metadata,
    add_litellm_data_to_request,
)
from litellm.types.utils import SupportedCacheControls


@pytest.fixture
def mock_request(monkeypatch):
    mock_request = Mock(spec=Request)
    mock_request.query_params = {}  # Set mock query_params to an empty dictionary
    mock_request.headers = {"traceparent": "test_traceparent"}
    monkeypatch.setattr(
        "litellm.proxy.litellm_pre_call_utils.add_litellm_data_to_request", mock_request
    )
    return mock_request


@pytest.mark.parametrize("endpoint", ["/v1/threads", "/v1/thread/123"])
@pytest.mark.asyncio
async def test_add_litellm_data_to_request_thread_endpoint(endpoint, mock_request):
    mock_request.url.path = endpoint
    user_api_key_dict = UserAPIKeyAuth(
        api_key="test_api_key", user_id="test_user_id", org_id="test_org_id"
    )
    proxy_config = Mock()

    data = {}
    await add_litellm_data_to_request(
        data, mock_request, user_api_key_dict, proxy_config
    )

    print("DATA: ", data)

    assert "litellm_metadata" in data
    assert "metadata" not in data


@pytest.mark.parametrize(
    "endpoint", ["/chat/completions", "/v1/completions", "/completions"]
)
@pytest.mark.asyncio
async def test_add_litellm_data_to_request_non_thread_endpoint(endpoint, mock_request):
    mock_request.url.path = endpoint
    user_api_key_dict = UserAPIKeyAuth(
        api_key="test_api_key", user_id="test_user_id", org_id="test_org_id"
    )
    proxy_config = Mock()

    data = {}
    await add_litellm_data_to_request(
        data, mock_request, user_api_key_dict, proxy_config
    )

    print("DATA: ", data)

    assert "metadata" in data
    assert "litellm_metadata" not in data


# test adding traceparent


@pytest.mark.parametrize(
    "endpoint", ["/chat/completions", "/v1/completions", "/completions"]
)
@pytest.mark.asyncio
async def test_traceparent_not_added_by_default(endpoint, mock_request):
    """
    This tests that traceparent is not forwarded in the extra_headers

    We had an incident where bedrock calls were failing because traceparent was forwarded
    """
    from litellm.integrations.opentelemetry import OpenTelemetry

    otel_logger = OpenTelemetry()
    setattr(litellm.proxy.proxy_server, "open_telemetry_logger", otel_logger)

    mock_request.url.path = endpoint
    user_api_key_dict = UserAPIKeyAuth(
        api_key="test_api_key", user_id="test_user_id", org_id="test_org_id"
    )
    proxy_config = Mock()

    data = {}
    await add_litellm_data_to_request(
        data, mock_request, user_api_key_dict, proxy_config
    )

    print("DATA: ", data)

    _extra_headers = data.get("extra_headers") or {}
    assert "traceparent" not in _extra_headers

    setattr(litellm.proxy.proxy_server, "open_telemetry_logger", None)


@pytest.mark.parametrize(
    "request_tags", [None, ["request_tag1", "request_tag2", "request_tag3"]]
)
@pytest.mark.parametrize(
    "request_sl_metadata", [None, {"request_key": "request_value"}]
)
@pytest.mark.parametrize("key_tags", [None, ["key_tag1", "key_tag2", "key_tag3"]])
@pytest.mark.parametrize("key_sl_metadata", [None, {"key_key": "key_value"}])
@pytest.mark.parametrize("team_tags", [None, ["team_tag1", "team_tag2", "team_tag3"]])
@pytest.mark.parametrize("team_sl_metadata", [None, {"team_key": "team_value"}])
@pytest.mark.asyncio
async def test_add_key_or_team_level_spend_logs_metadata_to_request(
    mock_request,
    request_tags,
    request_sl_metadata,
    team_tags,
    key_sl_metadata,
    team_sl_metadata,
    key_tags,
):
    ## COMPLETE LIST OF TAGS
    all_tags = []
    if request_tags is not None:
        print("Request Tags - {}".format(request_tags))
        all_tags.extend(request_tags)
    if key_tags is not None:
        print("Key Tags - {}".format(key_tags))
        all_tags.extend(key_tags)
    if team_tags is not None:
        print("Team Tags - {}".format(team_tags))
        all_tags.extend(team_tags)

    ## COMPLETE SPEND_LOGS METADATA
    all_sl_metadata = {}
    if request_sl_metadata is not None:
        all_sl_metadata.update(request_sl_metadata)
    if key_sl_metadata is not None:
        all_sl_metadata.update(key_sl_metadata)
    if team_sl_metadata is not None:
        all_sl_metadata.update(team_sl_metadata)

    print(f"team_sl_metadata: {team_sl_metadata}")
    mock_request.url.path = "/chat/completions"
    key_metadata = {
        "tags": key_tags,
        "spend_logs_metadata": key_sl_metadata,
    }
    team_metadata = {
        "tags": team_tags,
        "spend_logs_metadata": team_sl_metadata,
    }
    user_api_key_dict = UserAPIKeyAuth(
        api_key="test_api_key",
        user_id="test_user_id",
        org_id="test_org_id",
        metadata=key_metadata,
        team_metadata=team_metadata,
    )
    proxy_config = Mock()

    data = {"metadata": {}}
    if request_tags is not None:
        data["metadata"]["tags"] = request_tags
    if request_sl_metadata is not None:
        data["metadata"]["spend_logs_metadata"] = request_sl_metadata

    print(data)
    new_data = await add_litellm_data_to_request(
        data, mock_request, user_api_key_dict, proxy_config
    )

    print("New Data: {}".format(new_data))
    print("all_tags: {}".format(all_tags))
    assert "metadata" in new_data
    if len(all_tags) == 0:
        assert "tags" not in new_data["metadata"], "Expected=No tags. Got={}".format(
            new_data["metadata"]["tags"]
        )
    else:
        assert new_data["metadata"]["tags"] == all_tags, "Expected={}. Got={}".format(
            all_tags, new_data["metadata"].get("tags", None)
        )

    if len(all_sl_metadata.keys()) == 0:
        assert (
            "spend_logs_metadata" not in new_data["metadata"]
        ), "Expected=No spend logs metadata. Got={}".format(
            new_data["metadata"]["spend_logs_metadata"]
        )
    else:
        assert (
            new_data["metadata"]["spend_logs_metadata"] == all_sl_metadata
        ), "Expected={}. Got={}".format(
            all_sl_metadata, new_data["metadata"]["spend_logs_metadata"]
        )
    # assert (
    #     new_data["metadata"]["spend_logs_metadata"] == metadata["spend_logs_metadata"]
    # )


@pytest.mark.parametrize(
    "callback_vars",
    [
        {
            "langfuse_host": "https://us.cloud.langfuse.com",
            "langfuse_public_key": "pk-lf-9636b7a6-c066",
            "langfuse_secret_key": "sk-lf-7cc8b620",
        },
        {
            "langfuse_host": "os.environ/LANGFUSE_HOST_TEMP",
            "langfuse_public_key": "os.environ/LANGFUSE_PUBLIC_KEY_TEMP",
            "langfuse_secret_key": "os.environ/LANGFUSE_SECRET_KEY_TEMP",
        },
    ],
)
def test_dynamic_logging_metadata_key_and_team_metadata(callback_vars):
    os.environ["LANGFUSE_PUBLIC_KEY_TEMP"] = "pk-lf-9636b7a6-c066"
    os.environ["LANGFUSE_SECRET_KEY_TEMP"] = "sk-lf-7cc8b620"
    os.environ["LANGFUSE_HOST_TEMP"] = "https://us.cloud.langfuse.com"
    user_api_key_dict = UserAPIKeyAuth(
        token="6f8688eaff1d37555bb9e9a6390b6d7032b3ab2526ba0152da87128eab956432",
        key_name="sk-...63Fg",
        key_alias=None,
        spend=0.000111,
        max_budget=None,
        expires=None,
        models=[],
        aliases={},
        config={},
        user_id=None,
        team_id="ishaan-special-team_e02dd54f-f790-4755-9f93-73734f415898",
        max_parallel_requests=None,
        metadata={
            "logging": [
                {
                    "callback_name": "langfuse",
                    "callback_type": "success",
                    "callback_vars": callback_vars,
                }
            ]
        },
        tpm_limit=None,
        rpm_limit=None,
        budget_duration=None,
        budget_reset_at=None,
        allowed_cache_controls=[],
        permissions={},
        model_spend={},
        model_max_budget={},
        soft_budget_cooldown=False,
        litellm_budget_table=None,
        org_id=None,
        team_spend=0.000132,
        team_alias=None,
        team_tpm_limit=None,
        team_rpm_limit=None,
        team_max_budget=None,
        team_models=[],
        team_blocked=False,
        soft_budget=None,
        team_model_aliases=None,
        team_member_spend=None,
        team_member=None,
        team_metadata={},
        end_user_id=None,
        end_user_tpm_limit=None,
        end_user_rpm_limit=None,
        end_user_max_budget=None,
        last_refreshed_at=1726101560.967527,
        api_key="7c305cc48fe72272700dc0d67dc691c2d1f2807490ef5eb2ee1d3a3ca86e12b1",
        user_role=LitellmUserRoles.INTERNAL_USER,
        allowed_model_region=None,
        parent_otel_span=None,
        rpm_limit_per_model=None,
        tpm_limit_per_model=None,
    )
    callbacks = _get_dynamic_logging_metadata(user_api_key_dict=user_api_key_dict)

    assert callbacks is not None

    for var in callbacks.callback_vars.values():
        assert "os.environ" not in var


@pytest.mark.parametrize(
    "allow_client_side_credentials, expect_error", [(True, False), (False, True)]
)
def test_is_request_body_safe_global_enabled(
    allow_client_side_credentials, expect_error
):
    from litellm import Router

    error_raised = False

    llm_router = Router(
        model_list=[
            {
                "model_name": "gpt-3.5-turbo",
                "litellm_params": {
                    "model": "gpt-3.5-turbo",
                    "api_key": os.getenv("OPENAI_API_KEY"),
                },
            }
        ]
    )
    try:
        is_request_body_safe(
            request_body={"api_base": "hello-world"},
            general_settings={
                "allow_client_side_credentials": allow_client_side_credentials
            },
            llm_router=llm_router,
            model="gpt-3.5-turbo",
        )
    except Exception as e:
        print(e)
        error_raised = True

    assert expect_error == error_raised


@pytest.mark.parametrize(
    "allow_client_side_credentials, expect_error", [(True, False), (False, True)]
)
def test_is_request_body_safe_model_enabled(
    allow_client_side_credentials, expect_error
):
    from litellm import Router

    error_raised = False

    llm_router = Router(
        model_list=[
            {
                "model_name": "fireworks_ai/*",
                "litellm_params": {
                    "model": "fireworks_ai/*",
                    "api_key": os.getenv("FIREWORKS_API_KEY"),
                    "configurable_clientside_auth_params": (
                        ["api_base"] if allow_client_side_credentials else []
                    ),
                },
            }
        ]
    )
    try:
        is_request_body_safe(
            request_body={"api_base": "hello-world"},
            general_settings={},
            llm_router=llm_router,
            model="fireworks_ai/my-new-model",
        )
    except Exception as e:
        print(e)
        error_raised = True

    assert expect_error == error_raised


def test_reading_openai_org_id_from_headers():
    from litellm.proxy.litellm_pre_call_utils import LiteLLMProxyRequestSetup

    headers = {
        "OpenAI-Organization": "test_org_id",
    }
    org_id = LiteLLMProxyRequestSetup.get_openai_org_id_from_headers(headers)
    assert org_id == "test_org_id"


@pytest.mark.parametrize(
    "headers, expected_data",
    [
        ({"OpenAI-Organization": "test_org_id"}, {"organization": "test_org_id"}),
        ({"openai-organization": "test_org_id"}, {"organization": "test_org_id"}),
        ({}, {}),
        (
            {
                "OpenAI-Organization": "test_org_id",
                "Authorization": "Bearer test_token",
            },
            {
                "organization": "test_org_id",
            },
        ),
    ],
)
def test_add_litellm_data_for_backend_llm_call(headers, expected_data):
    import json
    from litellm.proxy.litellm_pre_call_utils import LiteLLMProxyRequestSetup
    from litellm.proxy._types import UserAPIKeyAuth

    user_api_key_dict = UserAPIKeyAuth(
        api_key="test_api_key", user_id="test_user_id", org_id="test_org_id"
    )

    data = LiteLLMProxyRequestSetup.add_litellm_data_for_backend_llm_call(
        headers=headers,
        user_api_key_dict=user_api_key_dict,
        general_settings=None,
    )

    assert json.dumps(data, sort_keys=True) == json.dumps(expected_data, sort_keys=True)


def test_foward_litellm_user_info_to_backend_llm_call():
    import json

    litellm.add_user_information_to_llm_headers = True

    from litellm.proxy.litellm_pre_call_utils import LiteLLMProxyRequestSetup
    from litellm.proxy._types import UserAPIKeyAuth

    user_api_key_dict = UserAPIKeyAuth(
        api_key="test_api_key", user_id="test_user_id", org_id="test_org_id"
    )

    data = LiteLLMProxyRequestSetup.add_headers_to_llm_call(
        headers={},
        user_api_key_dict=user_api_key_dict,
    )

    expected_data = {
        "x-litellm-user_api_key_user_id": "test_user_id",
        "x-litellm-user_api_key_org_id": "test_org_id",
        "x-litellm-user_api_key_hash": "test_api_key",
    }

    assert json.dumps(data, sort_keys=True) == json.dumps(expected_data, sort_keys=True)


def test_update_internal_user_params():
    from litellm.proxy.management_endpoints.internal_user_endpoints import (
        _update_internal_user_params,
    )
    from litellm.proxy._types import NewUserRequest

    litellm.default_internal_user_params = {
        "max_budget": 100,
        "budget_duration": "30d",
        "models": ["gpt-3.5-turbo"],
    }

    data = NewUserRequest(user_role="internal_user", user_email="krrish3@berri.ai")
    data_json = data.model_dump()
    updated_data_json = _update_internal_user_params(data_json, data)
    assert updated_data_json["models"] == litellm.default_internal_user_params["models"]
    assert (
        updated_data_json["max_budget"]
        == litellm.default_internal_user_params["max_budget"]
    )
    assert (
        updated_data_json["budget_duration"]
        == litellm.default_internal_user_params["budget_duration"]
    )


@pytest.mark.asyncio
async def test_proxy_config_update_from_db():
    from litellm.proxy.proxy_server import ProxyConfig
    from pydantic import BaseModel

    proxy_config = ProxyConfig()

    pc = AsyncMock()

    test_config = {
        "litellm_settings": {
            "callbacks": ["prometheus", "otel"],
        }
    }

    class ReturnValue(BaseModel):
        param_name: str
        param_value: dict

    with patch.object(
        pc,
        "get_generic_data",
        new=AsyncMock(
            return_value=ReturnValue(
                param_name="litellm_settings",
                param_value={
                    "success_callback": "langfuse",
                },
            )
        ),
    ):
        new_config = await proxy_config._update_config_from_db(
            prisma_client=pc,
            config=test_config,
            store_model_in_db=True,
        )

        assert new_config == {
            "litellm_settings": {
                "callbacks": ["prometheus", "otel"],
                "success_callback": "langfuse",
            }
        }


def test_prepare_key_update_data():
    from litellm.proxy.management_endpoints.key_management_endpoints import (
        prepare_key_update_data,
    )
    from litellm.proxy._types import UpdateKeyRequest

    existing_key_row = MagicMock()
    data = UpdateKeyRequest(key="test_key", models=["gpt-4"], duration="120s")
    updated_data = prepare_key_update_data(data, existing_key_row)
    assert "expires" in updated_data

    data = UpdateKeyRequest(key="test_key", metadata={})
    updated_data = prepare_key_update_data(data, existing_key_row)
    assert updated_data["metadata"] == {}

    data = UpdateKeyRequest(key="test_key", metadata=None)
    updated_data = prepare_key_update_data(data, existing_key_row)
    assert updated_data["metadata"] == None


@pytest.mark.parametrize(
    "env_value, expected_url",
    [
        (None, "/redoc"),  # default case
        ("/custom-redoc", "/custom-redoc"),  # custom URL
        ("https://example.com/redoc", "https://example.com/redoc"),  # full URL
    ],
)
def test_get_redoc_url(env_value, expected_url):
    if env_value is not None:
        os.environ["REDOC_URL"] = env_value
    else:
        os.environ.pop("REDOC_URL", None)  # ensure env var is not set

    result = _get_redoc_url()
    assert result == expected_url


@pytest.mark.parametrize(
    "env_vars, expected_url",
    [
        ({}, "/"),  # default case
        ({"DOCS_URL": "/custom-docs"}, "/custom-docs"),  # custom URL
        (
            {"DOCS_URL": "https://example.com/docs"},
            "https://example.com/docs",
        ),  # full URL
        ({"NO_DOCS": "True"}, None),  # docs disabled
    ],
)
def test_get_docs_url(env_vars, expected_url):
    # Clear relevant environment variables
    for key in ["DOCS_URL", "NO_DOCS"]:
        os.environ.pop(key, None)

    # Set test environment variables
    for key, value in env_vars.items():
        os.environ[key] = value

    result = _get_docs_url()
    assert result == expected_url

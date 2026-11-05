from caseflow_agent.state_rank import state_rank


def test_prerequisite_only_after_observed_error():
    keys = ["set_wifi_status", "set_low_battery_mode_status", "get_current_timestamp"]
    schemas = {name: {"parameters": {"properties": {}}} for name in keys}
    scores = dict(zip(keys, [0.65, 0.61, 0.5]))
    assert state_rank(scores, schemas, []) == keys
    error = [
        {
            "name": "set_wifi_status",
            "error": True,
            "result": "Wifi cannot be turned on in low battery mode",
        }
    ]
    assert state_rank(scores, schemas, error)[0] == "set_low_battery_mode_status"


def test_returned_object_id_can_expose_followup_without_executing_a_write():
    schemas = {
        "add_reminder": {"parameters": {"properties": {"content": {}}}},
        "modify_reminder": {
            "parameters": {
                "properties": {"reminder_id": {}},
                "required": ["reminder_id"],
            }
        },
    }
    scores = {"add_reminder": 0.7, "modify_reminder": 0.65}
    observed = [
        {
            "name": "add_reminder",
            "error": False,
            "result": "'00000000-abcd-1234-abcd-123456789abc'",
        }
    ]
    assert state_rank(scores, schemas, observed)[0] == "modify_reminder"
    assert scores["add_reminder"] == 0.7


def test_native_rank_surfaces_index_check_after_pending_receipt():
    from caseflow_agent.state_rank import native_candidates

    scores = {
        "tickets.apply_operation": 0.78,
        "operations.verify": 0.74,
        "knowledge.apply_operation": 0.72,
        "workflow.status": 0.70,
        "operations.status": 0.69,
        "knowledge.index_status": 0.67,
    }
    assert "knowledge.index_status" not in native_candidates(scores, None)
    result = {
        "name": "knowledge.apply_operation",
        "result": {"ready": False, "receipt": {"state": "index_pending"}},
    }
    options = native_candidates(scores, result)
    assert len(options) == 5 and options[0] == "knowledge.index_status"

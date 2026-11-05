from caseflow_agent.caseflow_eval import parse_disposition

def test_status_wrapper_is_accepted_but_ambiguous_or_untyped_output_is_not():
    status = '{"disposition":"blocked","reason":"审批返回 rejected，未做写入"}'
    assert (
        parse_disposition("说明\n```json\n" + status + "\n```")["disposition"]
        == "blocked"
    )
    assert parse_disposition(status + "\n" + status) == {}
    for text in (
        "null",
        "[]",
        '"blocked"',
        '{"disposition":"blocked","reason":null}',
        '{"disposition":"completed","reason":"ok","untrusted_extra":true}',
    ):
        assert parse_disposition(text) == {}

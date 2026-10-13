"""
Known, documented gaps in the injection regex layer (see INTERVIEW_ANSWERS_v2.md,
"Still not fixed"). strict=True: if one of these starts passing, the test
fails so the documentation gets updated.
"""
import pytest

from backend.guardrails.injection_scanner import scan_text_for_injection
from tests import probes


@pytest.mark.xfail(strict=True, reason="regex layer is English-only; needs a multilingual classifier")
@pytest.mark.parametrize("probe", [probes.HINDI, probes.FRENCH], ids=["hindi", "french"])
def test_non_english_injection(probe):
    assert scan_text_for_injection(probe)["flagged"]


@pytest.mark.xfail(strict=True, reason="paraphrased instructions need a semantic classifier on every chunk")
@pytest.mark.parametrize("probe", [probes.PARAPHRASE, probes.VERIFIER_TARGETED],
                         ids=["paraphrase", "verifier-targeted"])
def test_semantic_injection(probe):
    assert scan_text_for_injection(probe)["flagged"]


@pytest.mark.xfail(strict=True, reason="plain links are not flagged; needs output-side link allowlisting")
def test_plain_markdown_link():
    assert scan_text_for_injection(probes.MD_LINK)["flagged"]


@pytest.mark.xfail(strict=True, reason="chunks are scanned independently; needs assembled-context scan")
@pytest.mark.parametrize("probe", [probes.SPLIT_A, probes.SPLIT_B], ids=["split-a", "split-b"])
def test_split_instruction(probe):
    assert scan_text_for_injection(probe)["flagged"]

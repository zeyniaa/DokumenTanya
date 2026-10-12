"""Small deterministic metrics for manually labeled OCR/retrieval datasets."""
import re


def normalize(text):
    return re.sub(r"\s+", " ", text).strip()


def edit_distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, left in enumerate(reference, start=1):
        current = [i]
        for j, right in enumerate(hypothesis, start=1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def error_rates(reference, hypothesis):
    reference, hypothesis = normalize(reference), normalize(hypothesis)
    if not reference:
        raise ValueError("Reference transcription must not be empty.")
    return {"cer": edit_distance(reference, hypothesis) / len(reference),
            "wer": edit_distance(reference.split(), hypothesis.split()) / len(reference.split())}


def evidence_recall(expected_ids, retrieved_ids):
    expected = set(expected_ids)
    if not expected:
        raise ValueError("Ground truth evidence must not be empty.")
    return len(expected & set(retrieved_ids)) / len(expected)

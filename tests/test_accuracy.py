"""The accuracy metric, with nothing running.

A metric is easy to get subtly wrong in the flattering direction, so these tests
mostly check that it does NOT forgive things it should count.
"""
from domain.accuracy import aggregate, levenshtein, measure, normalise, percentile


# --- edit distance -------------------------------------------------------------

def test_identical_strings_have_no_distance():
    assert levenshtein("Anjali Bhosle", "Anjali Bhosle") == 0


def test_each_edit_type_counts_once():
    assert levenshtein("cat", "cot") == 1      # substitution
    assert levenshtein("cat", "cats") == 1     # insertion
    assert levenshtein("cats", "cat") == 1     # deletion


def test_distance_against_empty_is_the_length():
    assert levenshtein("", "abcd") == 4
    assert levenshtein("abcd", "") == 4


def test_distance_is_symmetric():
    assert levenshtein("Bhosle", "Bhosale") == levenshtein("Bhosale", "Bhosle")


def test_devanagari_is_compared_by_character():
    assert levenshtein("मीरा जोशी", "मीरा जोशी") == 0
    assert levenshtein("मीरा", "मौरा") == 1


# --- normalisation, and what it refuses to forgive ------------------------------

def test_line_wrapping_is_forgiven():
    """Rasterising rewraps lines; that is layout, not an OCR mistake."""
    assert normalise("Complainant Name:\nAnjali") == normalise("Complainant Name: Anjali")


def test_case_is_not_forgiven():
    """Lowercasing would flatter the score. A name is case-sensitive."""
    assert normalise("Anjali") != normalise("anjali")


def test_punctuation_is_not_forgiven():
    """A misread digit or separator in a phone number is a real error."""
    assert normalise("0900-000101") != normalise("0900000101")


# --- measurement ----------------------------------------------------------------

def test_a_perfect_read_scores_zero():
    m = measure(document="d", language="eng", method="tesseract_ocr",
                truth="Anjali Bhosle", observed="Anjali Bhosle")
    assert m.cer == 0.0


def test_one_wrong_character_in_thirteen():
    m = measure(document="d", language="eng", method="tesseract_ocr",
                truth="Anjali Bhosle", observed="Anjali Bhosie")
    assert m.errors == 1
    assert 0.07 < m.cer < 0.08


def test_empty_truth_does_not_divide_by_zero():
    assert measure(document="d", language="eng", method="tesseract_ocr",
                   truth="", observed="anything").cer == 0.0


# --- aggregation ----------------------------------------------------------------

def test_aggregate_weights_by_characters_not_by_document():
    """A short bad document must not outweigh a long clean one.

    Averaging per-document rates here would give (50% + 1%)/2 = 25.5%, which is not
    what the corpus says: 51 errors in 1010 characters is about 5%.
    """
    short = measure("short", "eng", "tesseract_ocr", truth="a" * 10, observed="b" * 5 + "a" * 5)
    long_ = measure("long", "eng", "tesseract_ocr",
                    truth="a" * 1000, observed="b" + "a" * 999)
    result = aggregate([short, long_])["eng"]
    assert result["documents"] == 2
    assert result["truth_chars"] == 1010
    assert 0.004 < result["cer"] < 0.01, result["cer"]


def test_languages_are_reported_separately():
    result = aggregate([
        measure("a", "eng", "tesseract_ocr", truth="abcd", observed="abcd"),
        measure("b", "hin", "tesseract_ocr", truth="मीरा", observed="मौरा"),
    ])
    assert set(result) == {"eng", "hin"}
    assert result["eng"]["cer"] == 0.0
    assert result["hin"]["cer"] > 0


# --- percentiles ------------------------------------------------------------------

def test_percentiles_of_a_small_sample():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 50) == 3.0
    assert percentile(values, 100) == 5.0


def test_percentile_of_nothing_is_zero_not_an_error():
    assert percentile([], 95) == 0.0


def test_percentile_never_indexes_out_of_range():
    for n in range(1, 12):
        values = [float(i) for i in range(n)]
        for p in (0, 1, 50, 95, 99, 100):
            assert percentile(values, p) in values

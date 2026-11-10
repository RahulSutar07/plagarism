from pipeline.evasion import detect_and_clean_evasion


def test_zero_width_character_removal():
    # Hidden zero width space between letters
    text_with_zw = "pla\u200bgiar\u200cism det\u200dection\ufeff"
    res = detect_and_clean_evasion(text_with_zw)
    assert res.cleaned_text == "plagiarism detection"
    assert res.zero_width_count == 4
    assert any("hidden/zero-width" in f for f in res.flags)


def test_homoglyph_normalization():
    # 'а' is Cyrillic (U+0430), 'о' is Cyrillic (U+043E), 'р' is Cyrillic (U+0440)
    text_with_cyrillic = "plаgiаrism repоrt соmраny"
    res = detect_and_clean_evasion(text_with_cyrillic)
    assert "plagiarism" in res.cleaned_text
    assert "report" in res.cleaned_text
    assert "company" in res.cleaned_text
    assert res.homoglyphs_fixed >= 4
    assert any("homoglyphic" in f for f in res.flags)


def test_spaced_letters_detection():
    # 'p l a g i a r i s m' (11 letters with spaces)
    evasive_text = "The issue of p l a g i a r i s m in student research is growing."
    res = detect_and_clean_evasion(evasive_text)
    assert "plagiarism" in res.cleaned_text
    assert res.spaced_runs_count == 1
    assert any("letter-spaced evasion" in f for f in res.flags)


def test_clean_text_leaves_standard_text_untouched():
    normal_text = "This is a clean, standard English academic paper without any evasion tricks."
    res = detect_and_clean_evasion(normal_text)
    assert res.cleaned_text == normal_text
    assert len(res.flags) == 0
    assert res.zero_width_count == 0
    assert res.homoglyphs_fixed == 0

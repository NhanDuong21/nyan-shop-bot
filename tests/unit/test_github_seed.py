from scripts import github_seed


def test_all_seed_issue_sequence_fields_are_real_tuples() -> None:
    github_seed.validate_issue_specs()


def test_nsb_014_uses_the_ui_feature_boundary() -> None:
    issue = next(spec for spec in github_seed.ISSUES if spec.code == "NSB-014")

    assert issue.files == ("admin/src/features/admin-dashboard/**",)

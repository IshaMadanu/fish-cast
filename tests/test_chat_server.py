import csv

from scripts.chat_server import build_historical_context


def test_build_historical_context_summarizes_observed_hauls_by_year(tmp_path):
    haul_data = tmp_path / "krillcast_merged.csv"
    with haul_data.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["DATE", "LATITUDE", "LONGITUDE", "NUMBER_OF_KRILL_UNDER_1M2", "SST"],
        )
        writer.writeheader()
        writer.writerows(
            [
                {"DATE": "2000-01-15", "LATITUDE": "-60", "LONGITUDE": "10", "NUMBER_OF_KRILL_UNDER_1M2": "0", "SST": "1"},
                {"DATE": "2000-02-15", "LATITUDE": "-65", "LONGITUDE": "20", "NUMBER_OF_KRILL_UNDER_1M2": "4", "SST": "3"},
                {"DATE": "2001-01-15", "LATITUDE": "-70", "LONGITUDE": "30", "NUMBER_OF_KRILL_UNDER_1M2": "6", "SST": ""},
            ]
        )

    context = build_historical_context(haul_data)

    assert context["source_file"] == haul_data.name
    assert context["data_type"].startswith("historical observed")
    assert context["total_hauls"] == 3
    assert context["date_range"] == {"first": "2000-01-15", "last": "2001-01-15"}
    assert context["overall"]["observed_field_summaries"]["NUMBER_OF_KRILL_UNDER_1M2"]["mean"] == 10 / 3
    assert [year["year"] for year in context["by_year"]] == ["2000", "2001"]
    first_year = context["by_year"][0]
    assert first_year["hauls"] == 2
    assert first_year["nonzero_krill_hauls"] == 1
    assert first_year["nonzero_krill_fraction"] == 0.5
    assert first_year["observed_field_summaries"]["SST"]["mean"] == 2
    assert first_year["highest_catch_hauls"][0] == {
        "date": "2000-02-15",
        "krill_per_m2": 4,
        "latitude": -65.0,
        "longitude": 20.0,
    }


def test_build_historical_context_rejects_non_haul_csv(tmp_path):
    haul_data = tmp_path / "not_haul_data.csv"
    haul_data.write_text("forecast_year,predicted_density\n2040,5\n", encoding="utf-8")

    try:
        build_historical_context(haul_data)
    except ValueError as error:
        assert "DATE" in str(error)
    else:
        raise AssertionError("Expected forecast CSV to be rejected as haul data")

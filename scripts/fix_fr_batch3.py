"""FR batch3 fixes: curated re-sync + INSEE population + cleanups."""
import os, sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.db import supabase as sb, upsert_data_points, datapoints_to_rows
from pipeline.base_provider import DataPoint


def fix_curated_stale_health():
    """Delete stale 2022 medical-doctors and nurses rows; yaml already has 2021 correct values."""
    for slug in ['medical-doctors', 'nurses']:
        r = sb.table('data_points').delete().eq('country','FR').eq('indicator',slug).eq('date','2022-12-31').execute()
        print(f"deleted {slug} 2022 rows")


def fix_population_via_insee():
    """Replace worldbank with INSEE BDM POPULATION-STRUCTURE IDBANK 001641586 (FR FE total)."""
    from pynsee.macrodata import get_series

    df = get_series(['001641586']).dropna(subset=['OBS_VALUE'])
    print(f"INSEE population: {len(df)} rows")

    points = []
    for _, row in df.iterrows():
        period_str = str(row.get('TIME_PERIOD'))
        if not period_str or len(period_str) != 4:
            continue
        try:
            yr = int(period_str)
            val = float(row['OBS_VALUE']) / 1_000_000  # Million
        except (ValueError, TypeError):
            continue
        points.append(DataPoint(
            indicator='population',
            country='FR',
            date=date(yr, 12, 31),
            value=round(val, 4),
            source='insee',
            unit='Million',
            series_id='POPULATION-STRUCTURE:001641586',
            adjustment='NSA',
        ))
    print(f"Built {len(points)} points; latest: {points[-1] if points else 'none'}")

    # Switch indicator_sources to insee, mark worldbank inactive
    existing_wb = sb.table('indicator_sources').select('*').eq('country','FR').eq('indicator','population').eq('source','worldbank').execute().data
    if existing_wb:
        sb.table('indicator_sources').update({'is_default': False, 'active': False}).eq('country','FR').eq('indicator','population').eq('source','worldbank').execute()
        print('  marked worldbank inactive')

    existing_insee = sb.table('indicator_sources').select('*').eq('country','FR').eq('indicator','population').eq('source','insee').execute().data
    if existing_insee:
        sb.table('indicator_sources').update({
            'series_id': 'POPULATION-STRUCTURE:001641586',
            'is_default': True, 'active': True,
            'unit': 'Million', 'adjustment': 'NSA',
            'freq_hint': 'A', 'conversion': 1e-6,
            'note': 'INSEE BDM POPULATION-STRUCTURE IDBANK 001641586 (Population totale au 1er janvier, FR=FE).'
        }).eq('country','FR').eq('indicator','population').eq('source','insee').execute()
    else:
        sb.table('indicator_sources').insert({
            'country': 'FR', 'indicator': 'population',
            'source': 'insee', 'series_id': 'POPULATION-STRUCTURE:001641586',
            'is_default': True, 'active': True,
            'unit': 'Million', 'adjustment': 'NSA',
            'freq_hint': 'A', 'conversion': 1e-6, 'transform': '',
            'note': 'INSEE BDM POPULATION-STRUCTURE IDBANK 001641586 (Population totale au 1er janvier, FR=FE).'
        }).execute()

    # Delete worldbank data points for population
    sb.table('data_points').delete().eq('country','FR').eq('indicator','population').eq('source','worldbank').execute()
    # Upsert INSEE data
    rows = datapoints_to_rows(points)
    n = upsert_data_points(rows)
    print(f"  upserted {n} INSEE population rows")


def update_truth_yaml_verifications():
    """Mark batch3 entries that match TE as verified."""
    pass  # done manually


if __name__ == "__main__":
    fix_curated_stale_health()
    fix_population_via_insee()
    print("\nNow run: pipeline/.venv/Scripts/python -m pipeline.providers.curated")

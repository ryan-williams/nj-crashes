import geopandas as gpd
import pandas as pd
from dataclasses import dataclass, asdict
from geopandas import sjoin
from math import sqrt
from numpy import nan
from pandas import isna
from typing import Union, Tuple, Optional
from utz import cached_property, DF, sxs, err

from nj_crashes.geo import is_nj_ll, get_county_geometries
from nj_crashes.sri.mp05 import get_mp05_map
from njdot.data import cn2cc
from njdot.load import load_type, INDEX_NAME, pk_renames

Year = Union[str, int]
Years = Union[Year, list[Year]]

ksi_renames = {
    'Total Killed': 'tk',
    'Total Injured': 'ti',
    'Pedestrians Killed': 'pk',
    'Pedestrians Injured': 'pi',
    'Total Vehicles Involved': 'tv',
}
ksi_cols = list(ksi_renames.values())
road_renames = {
    'SRI (Standard Route Identifier)': 'sri',
    'Mile Post': 'mp',
    'Crash Location': 'road',
    'Location Direction': 'road_direction',
    'Cross Street Name': 'cross_street',
}
road_cols = list(road_renames.values())
renames = {
    'Date': 'dt',
    **pk_renames,
    'County Name': 'cn',
    'Municipality Name': 'mn',
    'Police Department Code': 'pdc',
    'Police Department': 'pdn',
    'Police Station': 'station',
    'Latitude': 'olat',
    'Longitude': 'olon',
    'Crash Type Code': 'crash_type',
    'Severity': 'severity',
    **road_renames,
    **ksi_renames,
    'Alcohol Involved': 'alcohol',
    'HazMat Involved': 'hazmat',
    'Route': 'route',
    'Road System': 'road_system',
    'Road Character': 'road_character',
    'Road Surface Type': 'road_surface',
    'Surface Condition': 'surface_condition',
    'Light Condition': 'light_condition',
    'Environmental Condition': 'env_condition',
    'Road Divided By': 'road_divided',
    'Temporary Traffic Control Zone': 'ttcz',
    'Distance To Cross Street': 'cross_street_distance',
    'Ramp To/From Route Name': 'ramp_route',
    'Ramp To/From Direction': 'ramp_direction',
    'Posted Speed': 'speed_limit',
    'Posted Speed Cross Street': 'speed_limit_cross',
    'Cell Phone In Use Flag': 'cell_phone',
    'Road Horizontal Alignment': 'horizontal_alignment',
    'Road Grade': 'road_grade',
    'First Harmful Event': 'first_harmful_event',
}
astype = {
    'tk': 'int8',
    'ti': 'int8',
    'pk': 'int8',
    'pi': 'int8',
    'tv': 'int8',
    'crash_type': 'Int8',
    'road_system': 'Int8',
    'road_character': 'Int8',
    'road_surface': 'Int8',
    'surface_condition': 'Int8',
    'light_condition': 'Int8',
    'env_condition': 'Int8',
    'road_divided': 'Int8',
    'ttcz': 'Int8',
    'cross_street_distance': 'Int16',
    'horizontal_alignment': 'Int8',
    'road_grade': 'Int8',
    'first_harmful_event': 'Int8',
    'mp': 'float32',  # TODO: can be imprecise when casted to float64 (e.g. in JS; 0.38999998569488525 instead of 0.39)
}


def map_year_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.drop(columns=['cn', 'mn'])
    df['pdn'] = df.pdn.apply(lambda pdn: pdn.title())
    df['olon'] = -df['olon']  # Longitudes all come in positive, but are actually supposed to be negative (NJ ⊂ [-76, -73])
    df['severity'] = df['severity'].apply(lambda s: s.lower())
    df['route'] = df['route'].replace('', nan).astype('Int16').replace(0, nan)
    df['ramp_route'] = df['ramp_route'].replace(r'^\?$', '', regex=True)
    for k in ['speed_limit', 'speed_limit_cross']:
        df[k] = df[k].replace('^(?:0|-1)?$', nan, regex=True).astype('Int8')
    df['cell_phone'] = df['cell_phone'].apply(lambda s: {'Y': True, 'N': False}[s])
    return df


def map_df(df: pd.DataFrame) -> pd.DataFrame:
    cg = get_county_geometries()
    df.index = df.index.astype('int32')
    df = df[['dt'] + [ c for c in df if c != 'dt' ]]

    err("crashes: merging olat/olon with county geometries")
    gdf = Crashes(df).gdf('o')
    joined = sjoin(gdf.df[['olat', 'olon', 'geometry']], cg)
    joined = joined.rename(columns={ 'index_right': 'ocn', })
    with_ocn = sxs(gdf.df, joined.ocn).sort_index()
    occ = with_ocn.ocn.map(cn2cc).astype('Int8').rename('occ')
    with_ocn = sxs(with_ocn, occ).drop(columns=['geometry', 'ocn'])

    err("crashes: geocoding SRI/MPs")
    ill = Crashes(with_ocn).mp_lls(append=True)
    err("crashes: merging ilat/ilon with county geometries")
    igdf = Crashes(ill).gdf('i')
    ij = sjoin(igdf.df[['geometry']], cg)
    ij = ij.rename(columns={ 'index_right': 'icn', })
    with_cns = sxs(igdf.df, ij.icn).sort_index()
    icc = with_cns.icn.map(cn2cc).astype('Int8').rename('icc')
    with_cns = sxs(with_cns, icc).drop(columns=['geometry', 'icn'])

    return with_cns


def load(
    years: Years = None,
    county: str = None,
    read_pqt: Optional[bool] = None,
    write_pqt: bool = False,
    cols: Optional[list[str]] = None,
) -> pd.DataFrame:
    return load_type(
        tpe='Accidents',
        years=years,
        county=county,
        renames=renames,
        astype=astype,
        cols=cols,
        read_pqt=read_pqt,
        write_pqt=write_pqt,
        map_year_df=map_year_df,
        map_df=map_df,
    )


def geocode_mp(r, sris):
    sri = r.sri
    mp = r.mp
    if isna(sri):
        return dict(reason="No SRI")
    if isna(mp):
        return dict(reason="No MP")
    if sri not in sris:
        return dict(reason='SRI not found')
    mp_lls = sris[sri]
    ll = mp_lls.get(mp)
    if ll:
        return asdict(ll)
    else:
        return dict(reason="MP didn't geocode")


@dataclass
class Crashes:
    df: pd.DataFrame

    @classmethod
    def load(cls, *args, **kwargs) -> 'Crashes':
        return cls(load(*args, **kwargs))

    def gdf(self, tpe='') -> 'Crashes':
        df = self.df
        gdf = gpd.GeoDataFrame(
            df,
            geometry=gpd.points_from_xy(x=df[f'{tpe}lon'], y=df[f'{tpe}lat']),
            columns=df.columns,
        ).astype(df.dtypes)
        gdf.index.name = INDEX_NAME
        return Crashes(gdf)

    def mp_lls(self, append=True) -> pd.DataFrame:
        df = self.df
        mp05_map = get_mp05_map()
        ll = DF(
            sxs(df.sri, df.mp).apply(geocode_mp, sris=mp05_map, axis=1).tolist(),
            index=df.index,
        ).rename(columns={
            'lat': 'ilat',
            'lon': 'ilon',
        })
        if append:
            return sxs(df, ll)
        else:
            return ll

    def lls(self, default='io', types=None) -> 'LLCrashes':
        if types is None:
            # - interpolated (from SRI/MP)
            # - original (from crash report)
            # - interpolated, fall back to original
            # - original, fall back to interpolated
            types = [ 'oi' ]
            # types = [ 'i', 'o', 'io', 'oi', ]

        df = self.df.copy()
        mp05_map = get_mp05_map()
        ll = DF(sxs(df.sri, df.mp).apply(geocode_mp, sris=mp05_map, axis=1).tolist(), index=df.index)

        n = len(df)
        if len(ll) != n:
            raise RuntimeError(f"Expected {n} geocoded lls, got {len(ll)}")

        def replace(k, cross_tab=None):
            o = df[k].copy()
            i = ll[k]
            no_o = o.isna()
            yes_o = ~no_o
            num_no_o = no_o.sum()
            no_i = i.isna()
            yes_i = ~no_i
            num_yes_i = yes_i.sum()

            if cross_tab or (cross_tab is None and k == 'lat'):
                cross_tab_o = yes_o.apply(lambda b: "yes" if b else "no").rename("Original")
                cross_tab_i = yes_i.apply(lambda b: "yes" if b else "no").rename("Interpolated")
                crosstab = pd.crosstab(cross_tab_o, cross_tab_i)
                crosstab_pct = round(crosstab / n * 100, 1)
                err(f"Original {k} vs. interpolated {k}:")
                err(str(crosstab_pct))

            # Original lat/lon
            if 'o' in types:
                df[f'o{k}'] = o

            # Interpolated lat/lon
            if 'i' in types:
                df[f'i{k}'] = i

            # Original lat/lon, fall back to interpolated
            io = i.copy()
            io.loc[yes_o & no_i] = o
            if 'io' in types:
                df[f'io{k}'] = io

            # Interpolated lat/lon, fall back to original
            oi = o.copy()
            oi.loc[no_o & yes_i] = i
            if 'oi' in types:
                df[f'oi{k}'] = oi

            default_col = { 'i': i, 'o': o, 'io': io, 'oi': oi }[default]
            df[k] = default_col

        replace('lat')
        replace('lon')
        df = df[~df.lon.isna()]
        return LLCrashes(df)

    def __getattr__(self, item):
        return getattr(self.df, item)

    def __len__(self):
        return len(self.df)

    def __getitem__(self, item):
        return self.df[item]

    def __repr__(self):
        return repr(self.df)

    def _repr_html_(self):
        return self.df._repr_html_()


@dataclass
class LLCrashes(Crashes):
    df: pd.DataFrame

    @cached_property
    def nj_mask(self) -> pd.Series:
        return self.df.apply(lambda r: is_nj_ll(r.lat, r.lon), axis=1)

    @cached_property
    def njs(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        df = self.df
        nj_mask = self.nj_mask
        nnj = df[~nj_mask]
        nj = df[nj_mask]
        return nj, nnj

    @cached_property
    def nj(self) -> 'LLCrashes':
        return LLCrashes(self.njs[0])

    @cached_property
    def nnj(self) -> 'LLCrashes':
        return LLCrashes(self.njs[1])

    @cached_property
    def ll_hist(self):
        lls_count = self[['lon', 'lat', 'severity']].value_counts().rename('lls_count')
        merged = self.merge(lls_count.reset_index(), on=['lon', 'lat', 'severity'], how='left')
        merged['lls_count'] = merged['lls_count'].fillna(0)
        merged['radius'] = merged.lls_count.apply(sqrt)
        return LLCrashes(merged)

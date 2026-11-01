"""Week-41+ source boxes, with field-level TL/locked-price fallback.

Only import/build paths read workbook cells. Interactive routes keep reading
published snapshots. Presence is explicit: zero is a value, None is missing.
"""
from decimal import Decimal
import json
import re

from app.extensions import db
from app.models import IMSFact, IMSRawData
from app.services.tl_box_calculation_service import TLBoxCalculationService as Box

KEY = 'ims_unit_authority_v1'


def representative_name_key(value):
    from app.services.vacancy_matching import vacancy_identity
    from app.services.adaptive_kpi_target_authority import _norm
    vacancy=vacancy_identity(value)
    return 'VACANCY:'+vacancy[0] if vacancy else _norm(value)


def applies(year, month):
    return (int(year), int(month)) >= (2026, 10)


def invalidate():
    db.session.info.pop('_ims_unit_authority',None)


def _cache():
    # Session-local caches die when a snapshot helper releases its session;
    # they cannot survive into a later source/publication or web request.
    transaction=db.session().get_transaction()
    cache=db.session.info.get('_ims_unit_authority')
    if cache is None or cache.get('_transaction') is not transaction:
        cache={'_transaction':transaction}
        db.session.info['_ims_unit_authority']=cache
    return cache


def _expire_after_flush(session,_context):
    session.info.pop('_ims_unit_authority',None)


def _metadata(text):
    data=json.loads(text or '{}')
    return data.get(KEY) or {}


def source_units(year, month):
    """One bounded load per accepted source in the current application context."""
    if not applies(year,month):return {}
    from app.services.official_aggregate_service import OfficialAggregateService
    root=_cache();period=(int(year),int(month))
    periods=root.setdefault('period_sources',{})
    if period not in periods:periods[period]=OfficialAggregateService.latest_upload_id(year,month)
    source=periods[period]
    if not source:return {}
    cache=root.setdefault('sources',{})
    if source in cache:return cache[source]
    result={}
    for rid,pid,text in db.session.query(IMSFact.representative_id,IMSFact.product_id,IMSFact.metrics_json).filter_by(upload_id=source,report_type='brick_sales'):
        values=_metadata(text)
        if values:result[('REPRESENTATIVE',str(rid),int(pid))]=values
    for territory,pid,kind,text in db.session.query(IMSRawData.territory,IMSRawData.product_id,IMSRawData.sheet_type,IMSRawData.raw_json).filter(
        IMSRawData.upload_id==source,IMSRawData.sheet_type.in_(('official_target_aggregate','official_actual_aggregate'))):
        values=_metadata(text)
        if values:
            key=('AGGREGATE',str(territory),int(pid))
            if key in result and result[key]!=values:raise ValueError('Conflicting official box provenance')
            result[key]=values
    cache[source]=result
    return result


def _period_prices(year,month,product_ids):
    from app.services.product_unit_price_service import ProductUnitPriceService
    period=(int(year),int(month));cache=_cache().setdefault('prices',{}).setdefault(period,{})
    ids={int(pid) for pid in product_ids}
    if not cache:ids.update(key[-1] for key in source_units(year,month))
    missing=ids-set(cache)
    if missing:
        loaded=ProductUnitPriceService.price_map(missing,year,month)
        cache.update({pid:loaded.get(pid) for pid in missing})
    return cache


def resolve(year,month,scope,identity,pid,target_tl,actual_tl,price):
    values=source_units(year,month).get((scope,str(identity),int(pid)),{})
    output=[]
    for metric,tl in (('target',target_tl),('actual',actual_tl)):
        value=values.get(metric)
        if value is not None:
            number=Decimal(str(value))
            if not number.is_finite():raise ValueError('Invalid explicit IMS box value')
            output.append(Box.round_box(number))
        else:
            if Decimal(str(price or 0))<=0:raise ValueError('Missing locked price for IMS box fallback')
            output.append(Box.boxes_from_tl(tl,price))
    return output


def summary_rows(frame, products):
    """Read TTS summary identities and semantic product fields, never row offsets."""
    import pandas as pd
    from app.services.adaptive_kpi_target_authority import _norm
    identity=None
    for i in range(min(12,len(frame))):
        labels=[_norm(v) for v in frame.iloc[i].tolist()]
        if 'BOLGE' in labels and 'TTS' in labels and 'TTS BRICK' not in labels:
            identity=(i,labels.index('BOLGE'),labels.index('TTS'));break
    if identity is None:return None
    header,region_col,rep_col=identity
    columns={}
    for i in range(header):
        for j in range(frame.shape[1]):
            name=_norm(frame.iloc[i,j])
            if name not in products:continue
            # The product group is followed by target / output / realization.
            # Require semantic labels rather than accepting arbitrary numbers.
            target=actual=None
            for k in range(j,min(j+3,frame.shape[1])):
                labels=' '.join(_norm(frame.iloc[r,k]) for r in range(i+1,header))
                if 'HEDEF' in labels:target=k
                if 'CIKIS' in labels or 'GERCEKLESEN' in labels:actual=k
            if target is not None or actual is not None:columns[name]=(target,actual)
    if not columns:raise ValueError('TTS summary product metric headers unresolved')
    def number(value):
        if value is None or pd.isna(value) or str(value).strip() in ('','-','—'):return None
        if isinstance(value,bool):raise ValueError('Invalid boolean IMS unit')
        result=Decimal(str(value))
        if not result.is_finite():raise ValueError('Invalid IMS unit number')
        return float(result)
    result={};region=''
    for i in range(header+1,len(frame)):
        region_value=_norm(frame.iloc[i,region_col]);rep=_norm(frame.iloc[i,rep_col])
        if region_value:region=region_value
        if not rep:continue
        if rep in ('NATIONAL','TURKIYE TOPLAM','TURKIYE TOPLAMI'):
            identity=('AGGREGATE','NATIONAL')
        elif re.match(r'^\d{3}\b',rep):
            identity=('AGGREGATE',rep.split()[0])
        else:
            match=re.match(r'^(\d{3})\b',region)
            if not match:raise ValueError('TTS summary region identity unresolved')
            identity=('REPRESENTATIVE',match.group(1),representative_name_key(frame.iloc[i,rep_col]))
        for product,(target,actual) in columns.items():
            key=(*identity,product)
            if key in result:raise ValueError('Duplicate TTS summary source identity')
            result[key]={'target':number(frame.iloc[i,target]) if target is not None else None,
                         'actual':number(frame.iloc[i,actual]) if actual is not None else None}
    return result


def import_unit_values(importer, views):
    """Prefer supplied TTS summary cells, then supplied brick matrix cells.

    An absent cell is kept as None until a consumer resolves its TL fallback.
    Both layouts remain supported; no name/active-state roster substitution.
    """
    import pandas as pd
    from app.services.adaptive_kpi_target_authority import _norm,_matrix_plan,_source_rows
    products=set(views['products'])
    unit_reps,unit_aggregates={},{}
    if views.get('unit_name'):
        frame=pd.read_excel(importer.file_path,sheet_name=views['unit_name'],header=None)
        _products,aggregates,reps=_source_rows(frame,_matrix_plan(frame),track_presence=True)
        unit_reps=reps
        unit_aggregates={(territory,name):values for territory,name,values in aggregates}
    result={}
    def cells(values):
        result={metric:values.get(metric) if values.get(metric+'_present',False) else None
                for metric in ('target','actual')}
        result['source_sheet_by_metric']={metric:views.get('unit_name') if result[metric] is not None else None for metric in ('target','actual')}
        return result
    for identity,values in views['tl_reps'].items():
        for product in products:
            key=('REPRESENTATIVE',identity[0].split()[0],representative_name_key(identity[1]),product)
            result[key]=cells(unit_reps.get(identity,{}).get(product,{}))
    for identity,values in views['tl_aggregates'].items():
        for product in products:
            result[('AGGREGATE',identity[0],product)]=cells(unit_aggregates.get(identity,{}).get(product,{}))
    summary_names=[]
    for name,frame in (importer.workbook or {}).items():
        normalized=_norm(name)
        if normalized.startswith('1 TTS ') and 'KUTU' in normalized:summary_names.append(name)
    if len(summary_names)>1:raise ValueError('Ambiguous TTS unit summary sheet')
    if summary_names:
        summary_frame=pd.read_excel(importer.file_path,sheet_name=summary_names[0],header=None)
        source=summary_rows(summary_frame,products)
        if source is None:
            if summary_frame.dropna(how='all').empty:return result
            raise ValueError('TTS unit summary structure unresolved')
        if set(source)-set(result):raise ValueError('TTS unit summary contains unknown source identities')
        for key,values in source.items():
            for metric,value in values.items():
                if value is not None:
                    existing=result[key][metric]
                    if existing is not None and abs(float(existing)-float(value))>max(.01,abs(float(value))*1e-6):
                        raise ValueError('Conflicting explicit TTS summary and brick box values')
                    result[key][metric]=value
                    result[key]['source_sheet_by_metric'][metric]=summary_names[0]
    return result


def persist_import_units(importer,views,year,month):
    """Persist presence/provenance alongside existing source records atomically."""
    if not applies(year,month):return
    from collections import defaultdict
    from app.models import Target,IMSSummary
    from app.services.adaptive_kpi_target_authority import _norm
    from app.services.product_unit_price_service import ProductUnitPriceService as Prices
    values=getattr(importer,'_explicit_unit_values',None)
    if values is None:
        values=import_unit_values(importer,views)
        importer._explicit_unit_values=values
    pids={name:int(importer.resolve_product_match(name)['object'].id) for name in views['products']}
    prices=Prices.price_map(pids.values(),year,month)
    raw_rows=IMSRawData.query.filter_by(upload_id=importer.upload.id).all()
    identities=defaultdict(set)
    for row in raw_rows:
        if row.representative_id is not None:
            name=representative_name_key(row.representative)
            identities[(None,name)].add(int(row.representative_id))
            match=re.match(r'^(\d{3})\b',_norm(row.territory))
            if match:identities[(match.group(1),name)].add(int(row.representative_id))
    targets={(r.representative_id,r.product_id):r for r in Target.query.filter_by(year=year,month=month)}
    summaries={(r.representative_id,r.product_id):r for r in IMSSummary.query.filter_by(upload_id=importer.upload.id)}
    facts={(r.representative_id,r.product_id):r for r in IMSFact.query.filter_by(upload_id=importer.upload.id,report_type='brick_sales')}
    def effective(metadata,metric,tl,pid):
        explicit=metadata[metric]
        if explicit is not None:return float(explicit)
        price=prices.get(pid)
        if Decimal(str(price or 0))<=0:raise ValueError('Missing locked price for omitted source boxes')
        return float(Box.boxes_from_tl(tl,price))
    for (territory,name),products in views['tl_reps'].items():
        region=territory.split()[0];name_key=representative_name_key(name)
        ids=identities.get((region,name_key)) or identities[(None,name_key)]
        if len(ids)!=1:raise ValueError('Ambiguous source representative unit identity')
        rid=next(iter(ids))
        for product,pid in pids.items():
            metadata=values[('REPRESENTATIVE',region,name_key,product)]
            target=targets.get((rid,pid));fact=facts.get((rid,pid));summary=summaries.get((rid,pid))
            target_unit=effective(metadata,'target',products[product]['target'],pid)
            actual_unit=effective(metadata,'actual',products[product]['actual'],pid)
            if target is not None:
                target.unit_target=target_unit;target.unit_realization=actual_unit
            if summary is not None:
                summary.target_unit=target_unit;summary.unit=actual_unit
            if fact is not None:
                payload=json.loads(fact.metrics_json or '{}');payload[KEY]=metadata
                fact.metrics_json=json.dumps(payload,ensure_ascii=False)
                fact.unit=actual_unit
    for row in raw_rows:
        if row.sheet_type not in ('official_target_aggregate','official_actual_aggregate'):continue
        product=next((name for name,pid in pids.items() if pid==row.product_id),None)
        metadata=values.get(('AGGREGATE',str(row.territory),product))
        if metadata is None:raise ValueError('Missing official aggregate box identity')
        metric='target' if row.sheet_type=='official_target_aggregate' else 'actual'
        row.unit=effective(metadata,metric,row.tl,row.product_id)
        payload=json.loads(row.raw_json or '{}');payload[KEY]=metadata
        row.raw_json=json.dumps(payload,ensure_ascii=False)
    invalidate()
    db.session.flush()


def install_ims_unit_authority():
    """Apply after legacy repairs/optimizers, before any snapshot is built."""
    from app.services.production_result_service import ProductionResultService as Production
    from app.services.product_unit_price_service import ProductUnitPriceService as Prices
    from app.services.region_performance_service import RegionPerformanceService as Region
    from app.query.dashboard_query import DashboardQuery
    if getattr(Production,'_direct_ims_units_installed',False):return
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    if not event.contains(Session,'after_flush',_expire_after_flush):
        event.listen(Session,'after_flush',_expire_after_flush)

    def open_period(year,month):
        if not applies(year,month):return False
        period=(int(year),int(month));cache=_cache().setdefault('open_periods',{})
        if period not in cache:cache[period]=Production.final_upload(year,month) is None
        return cache[period]

    def representative_rows(rows,year,month,rid):
        if not open_period(year,month):return rows
        prices=_period_prices(year,month,rows.keys())
        repaired={}
        for pid,row in rows.items():
            item=dict(row)
            if str(item.get('source') or '')=='IMS' and not item.get('out_of_scope'):
                item['target_unit'],item['actual_unit']=resolve(year,month,'REPRESENTATIVE',rid,pid,item.get('target_tl'),item.get('actual_tl'),prices.get(pid))
                item['box_source']='IMS_DIRECT_UNIT_OR_TL_PERIOD_PRICE'
            repaired[pid]=item
        return repaired

    original_many=Production.effective_products.__func__
    original_one=Production.effective_product.__func__
    def many(cls,year,month,rid,product_ids=None):
        return representative_rows(original_many(cls,year,month,rid,product_ids),year,month,rid)
    def one(cls,year,month,rid,pid):
        row=original_one(cls,year,month,rid,pid)
        return representative_rows({int(pid):row},year,month,rid)[int(pid)]
    Production.effective_products=classmethod(many)
    Production.effective_product=classmethod(one)

    original_region_units=Region._official_region_unit_month
    def region_units(self,year,month):
        if not open_period(year,month):return original_region_units(self,year,month)
        official=self._official_ims_region_month(year,month)
        prices=_period_prices(year,month,official.keys())
        return {pid:[*resolve(year,month,'AGGREGATE',self.region_key,pid,target,actual,prices.get(pid)),complete]
                for pid,(target,actual,complete) in official.items()}
    Region._official_region_unit_month=region_units

    original_national=DashboardQuery.load_national_dashboard_metrics
    def national(self,filters=None):
        payload=original_national(self,filters)
        if not filters or not open_period(filters.year,filters.month):return payload
        products=payload.get('products') or []
        prices=_period_prices(filters.year,filters.month,[r['product_id'] for r in products])
        for row in products:
            pid=row['product_id']
            target,actual=resolve(filters.year,filters.month,'AGGREGATE','NATIONAL',pid,row['target_tl'],row['actual_tl'],prices.get(pid))
            row['unit_target'],row['unit_actual']=float(target),float(actual)
            row['unit_realization_percent']=round(float(actual*100/target),1) if target else 0.0
        payload['unit_target']=sum(r['unit_target'] for r in products)
        payload['unit_actual']=sum(r['unit_actual'] for r in products)
        payload['unit_realization_percent']=round(payload['unit_actual']*100/payload['unit_target'],2) if payload['unit_target'] else 0.0
        payload['box_source']='IMS_DIRECT_UNIT_OR_TL_PERIOD_PRICE'
        return payload
    DashboardQuery.load_national_dashboard_metrics=national

    original_map=DashboardQuery.load_region_performance
    def map_regions(self,filters=None):
        rows=original_map(self,filters)
        if not filters or not open_period(filters.year,filters.month):return rows
        from types import SimpleNamespace
        result=[]
        for row in rows:
            units=Region(str(row.region),filters.year,filters.month)._official_region_unit_month(filters.year,filters.month)
            if not units or not all(v[2] for v in units.values()):raise ValueError('Incomplete official IMS region map')
            item=dict(vars(row))
            item['unit_target']=sum(v[0] for v in units.values())
            item['unit_actual']=sum(v[1] for v in units.values())
            result.append(SimpleNamespace(**item))
        return result
    DashboardQuery.load_region_performance=map_regions
    from app.services.ims_import_service import IMSImportService
    original_finish=IMSImportService.finish
    def finish(self,*args,**kwargs):
        try:return original_finish(self,*args,**kwargs)
        finally:invalidate()
    IMSImportService.finish=finish
    Production._direct_ims_units_installed=True

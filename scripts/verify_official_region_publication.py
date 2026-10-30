"""Exact source/DB/published-view acceptance for the latest open IMS period."""
import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
import sqlalchemy as sa
from app import create_app
from app.extensions import db
from app.models import IMSUpload,IMSImportJob,IMSRawData,IMSFact,Target
from app.services.ims_import_service import IMSImportService
from app.services.adaptive_kpi_target_authority import _pair_views
from app.services.region_performance_service import RegionPerformanceService
from app.services.product_unit_price_service import ProductUnitPriceService
from app.services.tl_box_calculation_service import TLBoxCalculationService
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService,region_snapshot_sets
from app.services.persistent_representative_snapshot_service import PersistentRepresentativeSnapshotService,representative_snapshot_sets
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService


def main():
    app=create_app()
    failures=[]
    counts=defaultdict(int)
    def equal(actual,expected,context):
        if actual is None or abs(Decimal(str(actual))-Decimal(str(expected)))>Decimal('0.011'):
            failures.append(dict(context=context,actual=actual,expected=str(expected)))
    with app.app_context():
        db.session.execute(sa.text('PRAGMA query_only=ON'))
        upload=IMSUpload.query.filter_by(status='COMPLETED').order_by(IMSUpload.year.desc(),IMSUpload.month.desc(),IMSUpload.week_number.desc(),IMSUpload.id.desc()).first()
        assert upload is not None
        year,month=int(upload.year),int(upload.month)
        job=IMSImportJob.query.filter_by(ims_upload_id=upload.id).order_by(IMSImportJob.id.desc()).first()
        assert job is not None and job.status=='COMPLETED'
        summary=json.loads(job.result_summary or '{}')
        assert summary.get('publication_ready') is True
        path=Path(app.config['UPLOAD_FOLDER'])/'ims_archive'/f'upload-{upload.id}.xlsx'
        assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==job.source_hash
        adapter=IMSImportService(str(path))
        names=pd.ExcelFile(path).sheet_names
        pair=[n for n in names if 'TTS-BR' in n and 'REAL-' in n]
        adapter.workbook=pd.read_excel(path,sheet_name=pair,header=None)
        views=_pair_views(adapter)
        assert views is not None
        product_ids={name:adapter.resolve_product_match(name)['object'].id for name in views['products']}
        prices=ProductUnitPriceService.price_map(product_ids.values(),year,month)
        official={(r.sheet_type,r.territory,r.product_id):r for r in IMSRawData.query.filter(IMSRawData.upload_id==upload.id,IMSRawData.sheet_type.in_(('official_target_aggregate','official_actual_aggregate')))}
        for identity,products in views['tl_aggregates'].items():
            territory=identity[0]
            for name,pid in product_ids.items():
                for metric,kind in (('target','official_target_aggregate'),('actual','official_actual_aggregate')):
                    row=official.get((kind,territory,pid))
                    assert row is not None, (territory,pid,kind)
                    equal(row.tl,products[name][metric],f'archive-db:{territory}:{pid}:{metric}:tl')
                    equal(row.unit,views['unit_aggregates'][identity][name][metric],f'archive-db:{territory}:{pid}:{metric}:raw-unit')
                    counts['source_records']+=1
        visible=PersistentRegionSnapshotService.get_active_all(year,month)
        expected_regions={k[0] for k in views['tl_aggregates'] if k[0]!='NATIONAL'}
        assert set(visible)==expected_regions
        region_set=PersistentRegionSnapshotService.visible_generation_id(year,month)
        source_id=db.session.execute(sa.select(region_snapshot_sets.c.source_upload_id).where(region_snapshot_sets.c.id==region_set)).scalar()
        assert int(source_id)==upload.id
        for region,payload in visible.items():
            service=RegionPerformanceService(region,year,month)
            periods=(payload.get('report') or {}).get('periods') or {}
            assert periods.get('monthly') and payload.get('market_analysis') is not None
            cache={}
            for key,period in periods.items():
                expected=defaultdict(lambda:[Decimal(0),Decimal(0),Decimal(0),Decimal(0),True])
                for span in period.get('months',[]):
                    ym=int(span['year']),int(span['month'])
                    if ym not in cache:
                        cache[ym]=service._official_ims_region_month(*ym),service._official_region_unit_month(*ym)
                    tl,units=cache[ym]
                    for pid,values in tl.items():
                        bucket=expected[pid];bucket[0]+=values[0];bucket[1]+=values[1]
                        u=units.get(pid)
                        if u is None or not u[2]:bucket[4]=False
                        else:bucket[2]+=u[0];bucket[3]+=u[1]
                rows={int(r['product_id']):r for r in period.get('products',[])}
                assert set(rows)==set(expected),(region,key,'product coverage')
                for pid,row in rows.items():
                    target,actual,ut,ua,complete=expected[pid]
                    for field,value in (('target_tl',target),('actual_tl',actual)):
                        equal(row.get(field),value,f'region:{region}:{key}:{pid}:{field}')
                    if complete:
                        for field,value in (('target_unit',ut),('actual_unit',ua),('unit_difference',ua-ut)):
                            equal(row.get(field),value,f'region:{region}:{key}:{pid}:{field}')
                    counts['region_period_product_rows']+=1
                if any(v=='REPRESENTATIVE_AGGREGATE' for v in (period.get('source_by_month') or {}).values()):
                    failures.append(dict(context=f'region:{region}:{key}:forbidden-representative-fallback'))
            counts['regions']+=1
            print('OFFICIAL_REGION_ACCEPTANCE|'+json.dumps(dict(region=region,periods=len(periods),failures=sum(f['context'].startswith(f'region:{region}:') for f in failures))))
        dashboard=PersistentDashboardSnapshotService.get_generation_for_source(year,month,upload.id,0)
        assert dashboard and isinstance(dashboard.get('competition_analysis'),dict)
        national={int(r['product_id']):r for r in (dashboard.get('executive_metrics') or {}).get('products',[])}
        assert set(national)==set(product_ids.values())
        for pid,row in national.items():
            t=official[('official_target_aggregate','NATIONAL',pid)].tl
            a=official[('official_actual_aggregate','NATIONAL',pid)].tl
            for field,value in (('target_tl',t),('actual_tl',a),('unit_target',TLBoxCalculationService.boxes_from_tl(t,prices[pid])),('unit_actual',TLBoxCalculationService.boxes_from_tl(a,prices[pid]))):
                equal(row.get(field),value,f'dashboard:{pid}:{field}')
            counts['national_products']+=1
        targets={(r.representative_id,r.product_id):r for r in Target.query.filter_by(year=year,month=month)}
        facts={(r.representative_id,r.product_id):r for r in IMSFact.query.filter_by(upload_id=upload.id,report_type='brick_sales')}
        rep_ids=sorted({r for r,p in facts})
        reps=PersistentRepresentativeSnapshotService.get_active_many(rep_ids,year,month)
        assert set(reps)==set(rep_ids)
        for rid,workspace in reps.items():
            monthly=((workspace.get('snapshots') or {}).get('monthly') or {})
            for row in monthly.get('products',[]):
                pid=int((row.get('product') or {}).get('id') or row.get('product_id'))
                t=targets[(rid,pid)].tl_target;a=facts[(rid,pid)].tl
                for field,value in (('target_tl',t),('actual_tl',a),('target_unit',TLBoxCalculationService.boxes_from_tl(t,prices[pid])),('actual_unit',TLBoxCalculationService.boxes_from_tl(a,prices[pid]))):
                    equal(row.get(field),value,f'representative:{rid}:{pid}:{field}')
                counts['representative_product_rows']+=1
        counts['representatives']=len(reps)
        result=dict(result='FAIL' if failures else 'PASS',upload_id=upload.id,week=upload.week_number,counts=dict(counts),failures=failures)
        print('OFFICIAL_PUBLICATION_ACCEPTANCE|'+json.dumps(result,default=str))
        db.session.rollback()
        return 1 if failures else 0


if __name__=='__main__':raise SystemExit(main())

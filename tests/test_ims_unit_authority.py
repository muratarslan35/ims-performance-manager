import json
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from app import create_app
from app.extensions import db
from app.models import IMSFact,IMSRawData,IMSSummary,IMSUpload,Product,Representative,Target
from app.services.ims_unit_authority import KEY,invalidate,resolve,summary_rows
from app.services.production_result_service import ProductionResultService
from app.services.region_performance_service import RegionPerformanceService


@pytest.fixture
def source(tmp_path):
    class Config:
        TESTING=True
        SECRET_KEY='source-unit-test'
        SQLALCHEMY_DATABASE_URI='sqlite://'
        SQLALCHEMY_TRACK_MODIFICATIONS=False
        UPLOAD_FOLDER=tmp_path/'uploads'
        REPORT_FOLDER=tmp_path/'reports'
        BACKUP_FOLDER=tmp_path/'backups'
        LOG_FOLDER=tmp_path/'logs'
    app=create_app(Config)
    with app.app_context():
        db.create_all()
        product=Product(product_code='DIRECT',product_name='Direct product',unit_price=10)
        rep=Representative(rep_code='R',rep_name='BOŞ KADRO',region='901',active=False)
        upload=IMSUpload(file_name='week41.xlsx',year=2026,month=10,week_number=41,status='COMPLETED')
        db.session.add_all([product,rep,upload]);db.session.flush()
        raw=IMSRawData(upload_id=upload.id,year=2026,month=10,sheet_name='source',sheet_type='brick_sales',
            representative_id=rep.id,representative=rep.rep_name,product_id=product.id,tl=500,unit=999,raw_json='{}')
        db.session.add(raw);db.session.flush()
        fact=IMSFact(upload_id=upload.id,raw_data_id=raw.id,year=2026,month=10,week_number=41,
            representative_id=rep.id,product_id=product.id,report_type='brick_sales',tl=500,unit=999,
            metrics_json=json.dumps({KEY:dict(target=12.5,actual=7)}))
        db.session.add_all([fact,Target(year=2026,month=10,representative_id=rep.id,product_id=product.id,tl_target=1000,unit_target=999),
            IMSSummary(upload_id=upload.id,year=2026,month=10,representative_id=rep.id,product_id=product.id,tl=500,unit=999)])
        for territory,units in (('901',dict(target=30,actual=20)),('NATIONAL',dict(target=40,actual=25))):
            for kind,tl in (('official_target_aggregate',1000),('official_actual_aggregate',500)):
                db.session.add(IMSRawData(upload_id=upload.id,year=2026,month=10,sheet_name='source',sheet_type=kind,
                    territory=territory,product_id=product.id,tl=tl,unit=999,raw_json=json.dumps({KEY:units})))
        db.session.commit()
        yield rep.id,product.id,fact
        db.session.remove();db.drop_all()


def test_direct_units_win_for_representative_region_national_and_map(source):
    rid,pid,_fact=source
    from app.query.dashboard_query import DashboardQuery
    from app.query.filters import DashboardFilterParams
    one=ProductionResultService.effective_product(2026,10,rid,pid)
    many=ProductionResultService.effective_products(2026,10,rid,[pid])[pid]
    assert (one['target_unit'],one['actual_unit'])==(12,7)
    assert (many['target_unit'],many['actual_unit'])==(12,7)
    region=RegionPerformanceService('901',2026,10).aggregate([(2026,10)])['products'][0]
    assert (region['target_tl'],region['actual_tl'])==(1000,500)
    assert (region['target_unit'],region['actual_unit'],region['unit_difference'])==(30,20,-10)
    filters=DashboardFilterParams(year=2026,month=10)
    national=DashboardQuery().load_national_dashboard_metrics(filters)
    assert (national['unit_target'],national['unit_actual'])==(40,25)
    assert (national['target_tl'],national['actual_tl'])==(1000,500)
    maprow=DashboardQuery().load_region_performance(filters)[0]
    assert (maprow.unit_target,maprow.unit_actual)==(30,20)


@pytest.mark.parametrize('values,expected',[
    (dict(target=0,actual=0),(0,0)),
    (dict(target=None,actual=7),(100,7)),
    (dict(target=12,actual=None),(12,50)),
    (dict(target=None,actual=None),(100,50)),
])
def test_presence_is_per_metric_and_explicit_zero_never_falls_back(source,values,expected):
    rid,pid,fact=source
    fact.metrics_json=json.dumps({KEY:values});db.session.commit();invalidate()
    row=ProductionResultService.effective_product(2026,10,rid,pid)
    assert (row['target_unit'],row['actual_unit'])==expected


def test_explicit_values_do_not_require_a_price_but_missing_values_do(source):
    rid,pid,fact=source
    assert resolve(2026,10,'REPRESENTATIVE',rid,pid,1000,500,None)==[12,7]
    fact.metrics_json=json.dumps({KEY:dict(target=None,actual=7)})
    db.session.commit();invalidate()
    with pytest.raises(ValueError,match='Missing locked price'):
        resolve(2026,10,'REPRESENTATIVE',rid,pid,1000,500,None)


def test_previous_period_is_not_given_new_direct_unit_policy(source):
    rid,pid,_fact=source
    assert resolve(2026,9,'REPRESENTATIVE',rid,pid,1000,500,10)==[100,50]


def test_late_production_closure_overrides_a_previously_cached_ims_source(source):
    from app.models import ProductionResultUpload,ProductionResult,ProductionRegionProductResult
    rid,pid,_fact=source
    assert ProductionResultService.effective_product(2026,10,rid,pid)['target_unit']==12
    upload=ProductionResultUpload(file_name='p2.xlsx',stored_file_name='p2.xlsx',source_hash='p'*64,
        year=2026,month=10,production_stage=2,status='APPLIED')
    db.session.add(upload);db.session.flush()
    db.session.add(ProductionResult(upload_id=upload.id,representative_id=rid,product_id=pid,
        target_tl=1000,actual_tl=800,target_unit=900,actual_unit=800,realization_percent=80))
    db.session.add(ProductionRegionProductResult(upload_id=upload.id,region_code='901',product_id=pid,
        target_tl=1000,actual_tl=800,target_unit=900,actual_unit=800,realization_percent=80,unit_realization_percent=89))
    db.session.flush()  # closure must work even before the writer commits
    row=ProductionResultService.effective_product(2026,10,rid,pid)
    assert row['source']=='PRODUCTION_2'
    assert (row['target_unit'],row['actual_unit'])==(900,800)
    region=RegionPerformanceService('901',2026,10)._official_region_unit_month(2026,10)[pid]
    assert region[:2]==[900,800]


def test_source_metadata_queries_are_bounded_across_repeated_product_reads(source):
    from sqlalchemy import event
    rid,pid,_fact=source
    seen=[]
    def record(_conn,_cursor,statement,_parameters,_context,_many):
        if 'ims_facts.metrics_json' in statement or 'ims_raw_data.raw_json' in statement:
            seen.append(statement)
    event.listen(db.engine,'before_cursor_execute',record)
    try:
        for _ in range(20):
            assert resolve(2026,10,'REPRESENTATIVE',rid,pid,1000,500,10)==[12,7]
    finally:event.remove(db.engine,'before_cursor_execute',record)
    assert len(seen)<=4


def test_summary_sheet_uses_semantic_headers_and_retains_zero_and_missing():
    frame=pd.DataFrame([
        [None,None,None,None,'DIRECT PRODUCT',None,None],
        [None,None,None,None,'ÜRÜN HEDEF','ÜRÜN ÇIKIŞ','REAL'],
        [None,'BÖLGE','İL','TTS',None,None,None],
        [None,None,None,'NATIONAL',30,20,None],
        [None,'901 DIYARBAKIR',None,'901 DIYARBAKIR',30,20,None],
        [None,'901 DIYARBAKIR',None,'BOŞ KADRO',0,None,None],
    ])
    result=summary_rows(frame,{'DIRECT PRODUCT'})
    assert result[('AGGREGATE','NATIONAL','DIRECT PRODUCT')]==dict(target=30,actual=20)
    assert result[('REPRESENTATIVE','901','VACANCY:BOŞ KADRO','DIRECT PRODUCT')]==dict(target=0,actual=None)


def test_tl_only_pair_is_optional_only_for_new_policy(monkeypatch):
    from app.services.adaptive_kpi_target_authority import _pair_views,_find_pair
    from tests.test_adaptive_kpi_target_authority import _v2_matrix
    frame=_v2_matrix('tl')
    workbook={'2-TTS-BRICK TL-REA%':frame}
    with pytest.raises(ValueError):_find_pair(workbook)
    monkeypatch.setattr(pd,'read_excel',lambda *args,**kwargs:{'2-TTS-BRICK TL-REA%':frame})
    importer=SimpleNamespace(workbook=workbook,file_path='unused',upload=SimpleNamespace(year=2026,month=10))
    views=_pair_views(importer)
    assert views['unit_name'] is None
    assert all(not p['target_present'] and not p['actual_present'] for products in views['unit_reps'].values() for p in products.values())


def test_tl_only_compatibility_does_not_invent_source_units(monkeypatch):
    from tests.test_adaptive_kpi_target_authority import _v2_matrix
    from app.services.kpi_workbook_compat import optional_unit_compat_workbook,build_canonical_brick_frame
    frame=_v2_matrix('tl')
    original={'2-TTS-BRICK TL-REA%':frame}
    monkeypatch.setattr(pd,'read_excel',lambda *args,**kwargs:original)
    compat,path,derived=optional_unit_compat_workbook(original,'unused')
    assert derived and path is None
    assert list(original)==['2-TTS-BRICK TL-REA%']
    canonical,_consumed=build_canonical_brick_frame(compat)
    assert canonical['TRAVAZOL TL ÇIKIŞ'].sum()>0
    assert canonical['TRAVAZOL KUTU ÇIKIŞ'].sum()==0


def test_v2_missing_detail_uses_supplied_summary_and_retains_explicit_zero():
    from tests.test_adaptive_kpi_target_authority import _v2_matrix
    from app.services.adaptive_kpi_target_authority import _source_rows,_matrix_plan
    frame=_v2_matrix('unit')
    frame.iloc[6,5]=None
    frame.iloc[5:,6]=0
    frame.iloc[3:5,6]=0
    _products,_aggregates,reps=_source_rows(frame,_matrix_plan(frame),track_presence=True)
    values=next(iter(reps.values()))['TRAVAZOL']
    assert values['target']==100 and values['target_present']
    assert values['actual']==0 and values['actual_present']


def test_summary_vacancy_identities_do_not_collapse_bos_and_bos_cedilla():
    frame=pd.DataFrame([
        [None,None,None,None,'DIRECT PRODUCT',None,None],
        [None,None,None,None,'ÜRÜN HEDEF','ÜRÜN ÇIKIŞ','REAL'],
        [None,'BÖLGE','İL','TTS',None,None,None],
        [None,'901 DIYARBAKIR',None,'BOS',10,2,None],
        [None,'901 DIYARBAKIR',None,'BOŞ',20,3,None],
    ])
    rows=summary_rows(frame,{'DIRECT PRODUCT'})
    assert rows[('REPRESENTATIVE','901','VACANCY:BOS','DIRECT PRODUCT')]['target']==10
    assert rows[('REPRESENTATIVE','901','VACANCY:BOŞ','DIRECT PRODUCT')]['target']==20


def test_import_metadata_persists_real_zero_and_derives_only_missing_actual(source):
    from app.services.ims_unit_authority import persist_import_units,representative_name_key
    rid,pid,fact=source
    upload=db.session.get(IMSUpload,fact.upload_id)
    name='DIRECT PRODUCT';rep_name=representative_name_key('BOŞ KADRO')
    values={('REPRESENTATIVE','901',rep_name,name):dict(target=0,actual=None),
            ('AGGREGATE','901',name):dict(target=30,actual=20),
            ('AGGREGATE','NATIONAL',name):dict(target=40,actual=25)}
    importer=SimpleNamespace(upload=upload,_explicit_unit_values=values,
        resolve_product_match=lambda _name:dict(object=db.session.get(Product,pid)))
    views=dict(products=[name],tl_reps={('901 DIYARBAKIR','BOŞ KADRO'):{name:dict(target=1000,actual=500)}})
    persist_import_units(importer,views,2026,10)
    assert json.loads(fact.metrics_json)[KEY]['actual'] is None
    assert fact.unit==50
    target=Target.query.filter_by(year=2026,month=10,representative_id=rid).one()
    assert target.unit_target==0
    result=ProductionResultService.effective_product(2026,10,rid,pid)
    assert (result['target_unit'],result['actual_unit'])==(0,50)


@pytest.mark.parametrize('box_fields,expected',[
    ('all',(100,40)),('none',(10,4)),('target_only',(100,4)),
    ('actual_only',(10,40)),('explicit_zero',(100,0)),
    ('summary_only',(80,20)),('conflict',None),
])
def test_actual_import_accepts_supplied_or_omitted_box_matrix(source,tmp_path,box_fields,expected):
    from tests.test_adaptive_kpi_target_authority import _v2_matrix
    from app.services.ims_import_service import IMSImportService
    from app.services.alias_service import AliasService
    rid,pid,_fact=source
    rep=db.session.get(Representative,rid);rep.rep_name='UNIT SOURCE TEST';rep.active=True
    db.session.commit();AliasService.clear()
    db.session.expunge(_fact)
    tl=_v2_matrix('tl').replace({'TRAVAZOL':'DIRECT PRODUCT','101 ISTANBUL':'901 DIYARBAKIR','AYŞE TEST':'UNIT SOURCE TEST'})
    path=tmp_path/'week41.xlsx'
    with pd.ExcelWriter(path) as writer:
        tl.to_excel(writer,sheet_name='2-TTS-BRICK HEDEF REAL-TL V2',header=False,index=False)
        if box_fields not in ('none','summary_only'):
            units=tl.copy(deep=True)
            if box_fields=='target_only':units.iloc[3:,6]=None
            if box_fields=='actual_only':units.iloc[3:,5]=None
            if box_fields=='explicit_zero':units.iloc[3:,6]=0
            units.to_excel(writer,sheet_name='2-TTS-BRICK HEDEF REAL-KUTU V2',header=False,index=False)
        if box_fields in ('summary_only','conflict'):
            summary=pd.DataFrame([
                [None,None,None,None,'DIRECT PRODUCT',None,None],
                [None,None,None,None,'ÜRÜN HEDEF','ÜRÜN ÇIKIŞ','REAL'],
                [None,'BÖLGE','İL','TTS',None,None,None],
                [None,None,None,'NATIONAL',80,20,None],
                [None,'901 DIYARBAKIR',None,'901 DIYARBAKIR',80,20,None],
                [None,'901 DIYARBAKIR',None,'UNIT SOURCE TEST',80,20,None],
            ])
            summary.to_excel(writer,sheet_name='1-TTS KUTU-REA%',header=False,index=False)
    service=IMSImportService(path)
    result=service.run(2026,10,clear_before_import=True,week_number=41)
    if expected is None:
        assert service.upload.status=='FAILED'
        assert Target.query.filter_by(year=2026,month=10,representative_id=rid,product_id=pid).one().tl_target==1000
        return
    assert service.upload.status=='COMPLETED'
    invalidate()
    effective=ProductionResultService.effective_product(2026,10,rid,pid)
    assert (effective['target_unit'],effective['actual_unit'])==expected

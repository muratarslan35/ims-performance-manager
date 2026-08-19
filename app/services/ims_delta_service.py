"""Audit a staged IMS upload against the previous completed IMS without mutating live data."""
from collections import defaultdict
from sqlalchemy import or_, desc
from app.models import IMSUpload, IMSRawData, IMSFact, IMSSummary, Target, CompetitionData


def _previous_upload(upload):
    return (IMSUpload.query.filter(IMSUpload.status=="COMPLETED", IMSUpload.id!=upload.id,
            or_(IMSUpload.year < upload.year,
                (IMSUpload.year==upload.year) & (IMSUpload.month < upload.month),
                (IMSUpload.year==upload.year) & (IMSUpload.month==upload.month) & (IMSUpload.week_number < upload.week_number)))
            .order_by(desc(IMSUpload.year),desc(IMSUpload.month),desc(IMSUpload.week_number),desc(IMSUpload.id)).first())

def _fact_map(upload_id):
    result=defaultdict(lambda:[0.0,0.0])
    for row in IMSFact.query.filter_by(upload_id=upload_id).all():
        key=(row.representative_id,row.product_id); result[key][0]+=float(row.unit or 0); result[key][1]+=float(row.tl or 0)
    return dict(result)

def _target_map(upload_id):
    result={}
    for row in Target.query.filter_by(upload_id=upload_id).all(): result[(row.representative_id,row.product_id)]=(float(row.target_unit or 0),float(row.target_tl or 0))
    return result

def _competition_count(upload_id): return CompetitionData.query.filter_by(upload_id=upload_id).count()
def _brick_map(upload_id):
    result={}
    for row in IMSRawData.query.filter_by(upload_id=upload_id,sheet_type="official_brick_spread_master").all():
        result[(row.representative,row.territory,row.raw_json)]=(float(row.unit or 0),float(row.tl or 0))
    return result

def _changed(old,new,tolerance=0.000001):
    keys=set(old)|set(new); return [key for key in keys if key not in old or key not in new or any(abs(a-b)>tolerance for a,b in zip(old[key],new[key]))]
def build_previous_ims_delta(importer):
    current=importer.upload; previous=_previous_upload(current)
    if previous is None:
        report={"previous_upload_id":None,"baseline":False,"representatives_added":0,"representatives_removed":0,"products_added":0,"products_removed":0,"sales_changed":0,"targets_changed":0,"brick_spread_changed":0,"competition_count_before":0,"competition_count_after":_competition_count(current.id)}
    else:
        old_facts=_fact_map(previous.id); new_facts=_fact_map(current.id); old_keys=set(old_facts); new_keys=set(new_facts)
        old_reps={k[0] for k in old_keys}; new_reps={k[0] for k in new_keys}; old_products={k[1] for k in old_keys}; new_products={k[1] for k in new_keys}
        report={"previous_upload_id":previous.id,"baseline":True,"representatives_added":len(new_reps-old_reps),"representatives_removed":len(old_reps-new_reps),"products_added":len(new_products-old_products),"products_removed":len(old_products-new_products),"sales_changed":len(_changed(old_facts,new_facts)),"targets_changed":len(_changed(_target_map(previous.id),_target_map(current.id))),"brick_spread_changed":len(_changed(_brick_map(previous.id),_brick_map(current.id))),"competition_count_before":_competition_count(previous.id),"competition_count_after":_competition_count(current.id)}
    importer.previous_ims_delta=report; importer.statistics["previous_ims_delta_changes"]=sum(report.get(k,0) for k in ("representatives_added","representatives_removed","products_added","products_removed","sales_changed","targets_changed","brick_spread_changed")); return report

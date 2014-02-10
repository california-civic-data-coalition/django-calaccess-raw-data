try:
    from calaccess.models import FilernameCd,  FilerFilingsCd, FilerLinksCd, ExpnCd, RcptCd, SmryCd
except:
    print 'you need to load the raw calaccess data app in order to populate this one'
from campaign_finance.models import  Committee, Contribution, Cycle, Expenditure, Filer, Filing, Stats, Summary
from django.db import connection, transaction
from dateutil.relativedelta import relativedelta
from django.db.models import Sum
from django.db.models import Q
import csv

def load():
    try:
        load_candidates()
        print 'load_candidates done'
    except:
        print 'FAILED on load_candidates'
    try:
        load_candidate_filings()
        print 'load_filings done'
    except:
        print 'FAILED on load_filings'
    try:
        load_summary()
        print 'load_summary done'
    except:
        print 'FAILED on load_summary'
    try:
        load_expenditures()
        print 'load_expenditures done'
    except:
        print 'FAILED on load_expenditures'
    try:
        load_contributions()
        print 'load_contributions done'
    except:
        print 'FAILED on load_contributions'
    try:
        load_candidate_stats()
        print 'load_candidate_stats done'
    except:
        print 'FAILED on load_candidate_stats'
    try:
        load_committee_stats()
        print 'committee_stats done'
    except:
        print 'FAILED on load_committee_stats'

def load_candidates():
    sql_candidate_filers = '''
        SELECT
        FILERS_CD.FILER_ID,
        FILER_TYPES_CD.DESCRIPTION
        FROM FILERS_CD INNER JOIN FILER_TO_FILER_TYPE_CD ON FILERS_CD.FILER_ID = FILER_TO_FILER_TYPE_CD.FILER_ID
                        INNER JOIN FILER_TYPES_CD ON FILER_TO_FILER_TYPE_CD.FILER_TYPE = FILER_TYPES_CD.FILER_TYPE 
        WHERE FILER_TYPES_CD.FILER_TYPE='8'
        GROUP BY 1,2
    '''
    c = connection.cursor()
    c.execute(sql_candidate_filers)
    rows = c.fetchall()
    for r in rows:
        insert = Filer()
        insert.filer_id = r[0]
        insert.status = r[1]
        insert.filer_type = 'cand'
        insert.save()
    
    candidate_name_errors = []
    for f in Filer.objects.all():
        # check to see if they ever filed a F450 or F460
        try:
            obj = FilernameCd.objects.filter(filer_id=f.filer_id)[0]
            f.name = (obj.namt + ' ' + obj.namf + ' ' + obj.naml + ' ' + obj.nams).strip()
            f.xref_filer_id = obj.xref_filer_id
            f.save()
        except:
            'CANDIDATE NAME INFO NOT IN FilernameCd for %sload_committee_stats()' % f.filer_id
            candidate_name_errors.append(f.filer_id)
        
        
        qs = FilerLinksCd.objects.filter(filer_id_a=f.filer_id)
        for q in qs:
            # check to see if linked committee ever filed a F450 or F460. If it hasn't, forget about it
            qs_filings = FilerFilingsCd.objects.filter(filer_id=q.filer_id_b)
            has_filings_we_care_about = False
            if qs_filings.filter(form_id='F460').count() > 0:
                has_filings_we_care_about = True
            elif qs_filings.filter(form_id='F450').count() > 0:
                has_filings_we_care_about = True
            
            # check to see if the committee is linked to multiple filers. If it is, forget about it
            linked_to_just_this_candidate = False
            if FilerLinksCd.objects.filter(filer_id_b=q.filer_id_b).values_list('filer_id_a', flat=True).distinct().count() == 1:
                linked_to_just_this_candidate = True
            
            # is the committee already in the Committee model?
            qs_existing_cmtees = Committee.objects.filter(filer_id_raw=q.filer_id_b)
            if qs_existing_cmtees.count() > 0:
                already_accounted_for = True
            else:
                already_accounted_for = False
            
            if already_accounted_for == False:
                if has_filings_we_care_about and linked_to_just_this_candidate == True:
                    qs_filer_name = FilernameCd.objects.filter(filer_id=q.filer_id_b)
                    if qs_filer_name.count() > 0:
                        insert = Committee()
                        insert.filer = f
                        insert.filer_id_raw = q.filer_id_b
                        filer_name_obj = FilernameCd.objects.filter(filer_id=q.filer_id_b)[0]
                        insert.name = (filer_name_obj.namt + ' ' + filer_name_obj.namf + ' ' + filer_name_obj.naml + ' ' + filer_name_obj.nams).strip()
                        insert.committee_type = 'ccrc'
                        insert.save()
                else:
                    print '%s is a no go' % q.filer_id_b
        
        # nuke filers with no filings
        if f.committee_set.count() == 0:
            print 'bye bye %s' % f.filer_id
            f.delete()
        
        # I should add something here that looks at the Statement of Organization or some other filing to get party affiliation and office sought that cycle
    return candidate_name_errors


def load_candidate_filings():
    for f in Filer.objects.all():
        for c in f.committee_set.all():
            # filer_id_raw preserves the CAL-ACCESS committee filer_id
            # the app accociates all candidate committees with the Candidate as the controlling filer for convenience
            # all PACs will have the same Filer.filing_id and Committee.filing_id_raw
            qs_filings = FilerFilingsCd.objects.filter(Q(form_id='F460') | Q(form_id='F450'), filer_id=c.filer_id_raw)
            for filing in qs_filings:
                qs_amends = qs_filings.filter(filing_id=filing.filing_id)
                if qs_amends.count() > 1:
                    current_filing = qs_amends.order_by('-filing_sequence')[0]
                    qs_check = Filing.objects.filter(committee=c, filing_id=current_filing.filing_id, amend_id=current_filing.filing_sequence)
                    if qs_check == 1:
                        print 'already accounted for filing'
                        continue
                else:
                    current_filing = filing
                    insert = Filing()
                    if current_filing.session_id % 2 == 0:
                        cycle_year = current_filing.session_id
                    else:
                        cycle_year = current_filing.session_id + 1
                    insert.cycle, created = Cycle.objects.get_or_create(name=cycle_year)
                    insert.committee = c
                    insert.filing_id = current_filing.filing_id
                    insert.amend_id = current_filing.filing_sequence
                    insert.form_id = current_filing.form_id
                    if current_filing.rpt_start:
                        insert.start_date = current_filing.rpt_start.isoformat()
                    if current_filing.rpt_end:
                        insert.end_date = current_filing.rpt_end.isoformat()
                    insert.save()

def load_summary():
    '''
        Currently using a dictonary to parse the summary information by form type, schedule and line number.
    '''
    summary_form_dict = {
        'F460': {
            #'name': 'Recipient Committee Campaign Statement',
            'itemized_monetary_contribs': {'sked': 'A', 'line_item': 1},
            'unitemized_monetary_contribs': {'sked': 'A', 'line_item': 2},
            'total_monetary_contribs': {'sked': 'A', 'line_item': 3},
            'non_monetary_contribs': {'sked': 'F460', 'line_item': 4},
            'total_contribs': {'sked': 'F460', 'line_item': 5},
            'itemized_expenditures': {'sked': 'E', 'line_item': 1},
            'unitemized_expenditures': {'sked': 'E', 'line_item': 2},
            'total_expenditures': {'sked': 'E', 'line_item': 4},
            'ending_cash_balance': {'sked': 'F460', 'line_item': 16},
            'outstanding_debts': {'sked': 'F460', 'line_item': 19},
        },
        'F450': {
            #'name': 'Recipient Committee Campaign Statement -- Short Form',
            'itemized_monetary_contribs': None,
            'unitemized_monetary_contribs': None,
            'total_monetary_contribs': {'sked': 'F450', 'line_item': 7},
            'non_monetary_contribs': {'sked': 'F450', 'line_item': 8},
            'total_contribs': {'sked': '450', 'line_item': 10},
            'itemized_expenditures': {'sked': 'F450', 'line_item': 1},
            'unitemized_expenditures': {'sked': 'F450', 'line_item': 2},
            'total_expenditures': {'sked': 'E', 'line_item': 6},
            'ending_cash_balance': {'sked': 'F460', 'line_item': 15},
            'outstanding_debts': None,
        }
    }
    for f in Filing.objects.all():
        qs = SmryCd.objects.filter(filing_id=f.filing_id, amend_id=f.amend_id)
        if qs.count() == 0:
            print 'no SmryCd data for Committee %s Filing %s Amend %s' % (f.committee.filer_id, f.filing_id, f.amend_id)
        else:
            query_dict = summary_form_dict[f.form_id]
            insert = Summary()
            insert.committee = f.committee
            insert.cycle = f.cycle
            insert.form_type = f.form_id
            insert.filing = f
            for k,v in query_dict.items():
                try:
                    insert.__dict__[k] = qs.get(form_type=v['sked'], line_item=v['line_item']).amount_a
                except:
                    insert.__dict__[k] = 0
            insert.save()

def load_expenditures():
    for f in Filing.objects.all():
        qs = ExpnCd.objects.filter(filing_id=f.filing_id, amend_id=f.amend_id)
        for q in qs:
            insert = Expenditure()
            insert.cycle = f.cycle
            insert.committee = f.committee
            insert.line_item = q.line_item
            insert.payee_nams = q.payee_nams
            insert.payee_namt = q.payee_namt
            insert.amend_id = q.amend_id
            insert.expn_dscr = q.expn_dscr
            insert.payee_zip4 = q.payee_zip4
            insert.g_from_e_f = q.g_from_e_f
            insert.payee_city = q.payee_city
            insert.amount = q.amount
            insert.memo_refno = q.memo_refno
            insert.expn_code = q.expn_code
            insert.memo_code = q.memo_code
            insert.payee_namf = q.payee_namf
            insert.entity_cd = q.entity_cd
            insert.filing_id = q.filing_id
            insert.bakref_tid = q.bakref_tid
            insert.payee_adr1 = q.payee_adr1
            insert.payee_adr2 = q.payee_adr2
            insert.expn_chkno = q.expn_chkno
            insert.form_type = q.form_type
            insert.cmte_id = q.cmte_id
            insert.xref_schnm = q.xref_schnm
            insert.xref_match = q.xref_match
            if q.expn_date:
                insert.expn_date = q.expn_date.isoformat()
            insert.cum_ytd = q.cum_ytd
            insert.payee_nams = q.payee_nams
            insert.tran_id = q.tran_idconn
            insert.payee_naml = q.payee_naml
            insert.name = (q.payee_namt + ' ' + q.payee_namf + ' ' + q.payee_naml + ' ' + q.payee_nams).strip()
            insert.save()
        

def load_contributions():
    for f in Filing.objects.all():
        qs = RcptCd.objects.filter(filing_id=f.filing_id, amend_id=f.amend_id)
        for q in qs:
            insert = Contribution()
            insert.cycle = f.cycle
            insert.committee = f.committee
            insert.ctrib_namt = q.ctrib_namt
            insert.ctrib_occ = q.ctrib_occ
            insert.ctrib_nams = q.ctrib_nams
            insert.line_item = q.line_item
            insert.amend_id = q.amend_id
            insert.rec_type = q.rec_type
            insert.ctrib_namf = q.ctrib_namf
            insert.date_thru = q.date_thru
            insert.ctrib_naml = q.ctrib_naml
            insert.ctrib_self = q.ctrib_self
            if q.rcpt_date:
                insert.rcpt_date = q.rcpt_date
            insert.ctrib_zip4 = q.ctrib_zip4
            insert.ctrib_st = q.ctrib_st
            insert.filing_id = q.filing_id
            insert.ctrib_adr1 = q.ctrib_adr1
            insert.ctrib_adr2 = q.ctrib_adr2
            insert.memo_refno = q.memo_refno
            insert.intr_st = q.intr_st
            insert.memo_code = q.memo_code
            insert.intr_self = q.intr_self
            insert.intr_occ = q.intr_occ
            insert.intr_emp = q.intr_emp
            insert.entity_cd = q.entity_cd
            insert.intr_cmteid = q.intr_cmteid
            insert.ctrib_city = q.ctrib_city
            insert.bakref_tid = q.bakref_tid
            insert.tran_type = q.tran_type
            insert.intr_adr2 = q.intr_adr2
            insert.cum_ytd = q.cum_ytd
            insert.intr_adr1 = q.intr_adr1
            insert.form_type = q.form_type
            insert.intr_city = q.intr_city
            insert.cmte_id = q.cmte_id
            insert.xref_schnm = q.xref_schnm
            insert.ctrib_emp = q.ctrib_emp
            insert.xref_match = q.xref_match
            insert.cum_oth = q.cum_oth
            insert.ctrib_dscr = q.ctrib_dscr
            insert.intr_namt = q.intr_namt
            insert.intr_nams = q.intr_nams
            insert.amount = q.amount
            insert.intr_naml = q.intr_naml
            insert.intr_zip4 = q.intr_zip4
            insert.intr_namf = q.intr_namf
            insert.tran_id = q.tran_id
            insert.name = (q.ctrib_namt + ' '+ q.ctrib_namf + ' ' + q.ctrib_naml + ' ' + q.ctrib_nams).strip()
            insert.save()

def load_candidate_stats():
    for f in Filer.objects.filter(filer_type='cand'):
        qs = Summary.objects.filter(committee__filer=f)
        if qs.count() > 0:
            for stat in Stats.STAT_TYPE_CHOICES:
                start_year = qs.order_by('filing__start_date')[0].filing.start_date
                end_year = qs.order_by('-filing__start_date')[0].filing.start_date
                insert = Stats()
                insert.stat_type = stat[0]
                insert.filer = f
                insert.filer_type = 'cand'
                insert.int_year_span =  relativedelta(end_year, start_year).years
                insert.str_year_span = '%s - %s' % (start_year.year, end_year.year)
                insert.amount = qs.aggregate(tot=Sum(stat[0]))['tot']
                insert.save()

def load_committee_stats():
    for f in Filer.objects.filter(filer_type='cand'):
        for c in f.committee_set.all():
            qs = Summary.objects.filter(committee=c)
            if qs.count() > 0:
                for stat in Stats.STAT_TYPE_CHOICES:
                    start_year = qs.order_by('filing__start_date')[0].filing.start_date
                    end_year = qs.order_by('-filing__start_date')[0].filing.start_date
                    insert = Stats()
                    insert.stat_type = stat[0]
                    insert.filer = f # keeping the filer linked to as the candidate filer
                    insert.filer_type = 'cand'
                    insert.int_year_span =  relativedelta(end_year, start_year).years
                    insert.str_year_span = '%s - %s' % (start_year.year, end_year.year)
                    insert.amount = qs.aggregate(tot=Sum(stat[0]))['tot']
                    insert.save()
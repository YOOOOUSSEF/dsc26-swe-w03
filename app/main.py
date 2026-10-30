"""Rawaj Pay transfer API. See README.md for the endpoints, errors and rules."""
import math
import uuid

import threading
bucket_lock = threading.Lock()
from fastapi import FastAPI,Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import update
from app.models import Transfer, Account, IdempotencyRecord

from app.db import make_engine, make_session_factory  # noqa: F401  (use these, do not edit app/db.py)
from app.settings import Settings
from pydantic import BaseModel,Field,ConfigDict

class CustomException(Exception):
    def __init__(self, title:str, status:int,headers:dict=None,errors:dict=None,detail:str=None):
        self.title,self.status,self.headers,self.errors,self.detail=title,status,headers,errors,detail

# helper function used in exception handler.
def problem(title,status,headers=None,errors=None, detail=None):
      body = {"type": "about:blank", "title": title, "status": status}


      if errors is not None: body['errors'] = errors
      if detail is not None: body['detail'] = detail

      return JSONResponse(content=body,status_code=status,headers=headers,media_type="application/problem+json")



def create_app(settings: Settings) -> FastAPI:
    """Return a new app.

    - Create the engine with make_engine(settings.database_url) and store it as
      app.state.engine (tests create the tables and seed accounts through it).
    - Use settings.api_tokens (token -> customer id) for authentication.
    - Use settings.clock (not time.time / time.monotonic directly) for the rate limiter.
    """
    class In_body_transfer(BaseModel):
        model_config=ConfigDict(extra='forbid',strict=True)

        from_account_id:str=Field(min_length=1,max_length=32,description='Sender Account ID')
        to_account_id:str=Field(min_length=1,max_length=32,description='Reciever Account ID')
        amount_piastres:int=Field(gt=0,le=settings.max_transfer_piastres,description='Amount sent in Cent')    
        memo:str|None=Field(max_length=140,default=None)

    # initialize bucket -> for each customer_id put tokens and last_refill time.
    bucket:dict[str,dict]={}  
    for customer_id in settings.api_tokens.values():
        bucket[customer_id]={}
        bucket[customer_id]['tokens']=settings.rate_limit_capacity
        bucket[customer_id]['last_refill']=settings.clock()

    app=FastAPI(title="Rawaj Transfer App")

    # Exception handler for any error I raise.
    @app.exception_handler(CustomException)
    def OnCustomException(request:Request,exec:CustomException):
      return problem(exec.title,exec.status,exec.headers,exec.errors,exec.detail)

    # Exception handler for Validation Error.
    @app.exception_handler(RequestValidationError)
    def OnValidationException(request:Request,exec:RequestValidationError):
        by_loc = {}
        for e in exec.errors():
            by_loc[tuple(e["loc"])]= {"loc": e["loc"], "msg": e["msg"]}   # one entry per field
        return problem("Invalid body",422, errors=list(by_loc.values()))

    # Engine creating and putting in app.
    engine=make_engine(settings.database_url)
    app.state.engine=engine

    # Authenticate middleware
    @app.middleware("http")
    async def customer_authentication(request:Request,call_next):
        token=request.headers.get("Authorization")

        # 1) missing header
        if token is None:
            return JSONResponse(
            status_code=401,
            content={"type": "about:blank", "title": "No Token", "status": 401},
            media_type="application/problem+json",headers={"WWW-Authenticate": "Bearer"}
            )
        token_arr=token.split() # split to Bearer and token_id.

        # 2) if insert some space, or No token_id, then detect it.
        if  len(token_arr)<=1:
            return JSONResponse(
            status_code=401,
            content={"type": "about:blank", "title": "No Token", "status": 401},
            media_type="application/problem+json",headers={"WWW-Authenticate": "Bearer"}
            )
        
        # 3) another schema Basic, Token, .....
        if  token_arr[0]!='Bearer':
            return JSONResponse(
            status_code=401,
            content={"type": "about:blank", "title": "Bad Token", "status": 401},
            media_type="application/problem+json",headers={"WWW-Authenticate": "Bearer"}
            )
            #raise CustomException(title='Bad Token',status=401,headers={'WWW-Authenticate':'Bearer'}) -> crash
        
        # 4) if token not in api_tokens then unknown.
        auth_customer_id=settings.api_tokens.get(token_arr[1])
        if auth_customer_id is None:
            return JSONResponse(
            status_code=401,
            content={"type": "about:blank", "title": "Unknown Token", "status": 401},
            media_type="application/problem+json",headers={"WWW-Authenticate": "Bearer"}
            )
        ### YOU are Authenticated.

        request.state.auth_source_id=auth_customer_id  # propagate to next req/middelware.

        # Rate Limiting
        if request.url.path=="/v1/transfers" and request.method == "POST":
          with bucket_lock:
            # 1) Rate limiting (Filling) 
            now=settings.clock()
            elapsed =max(0, now- bucket[auth_customer_id]["last_refill"]) # if clock goes backword, then = 0.

            bucket[auth_customer_id]['tokens']=min(
                settings.rate_limit_capacity,
                bucket[auth_customer_id]['tokens']+elapsed*settings.rate_limit_refill_per_second
            )# put fractional tokens (because algorithm says that) and also good accuracy.
            
            bucket[auth_customer_id]["last_refill"]=now

            # 2) Rate limiting (checking) ( I do not make it in middleware Because it is not on all endpoints)
            cus_tokens=bucket[auth_customer_id]['tokens']
            if cus_tokens < 1: # if user finishes his tokens.
                # time until 1 token completed.
                # settings.rate_limit_refill_per_second must be non zero.
                wait = math.ceil((1 - cus_tokens) / settings.rate_limit_refill_per_second) 
                header={'Retry-After':str(wait)} # The header value must be str in framework like FastApi.
                return JSONResponse(
                status_code=429,
                content={"type": "about:blank", "title": "You hitted the requests limit", "status": 429},
                media_type="application/problem+json",headers=header
                )
            else: # decrease token by 1
                bucket[auth_customer_id]['tokens']-=1


        

        response=await call_next(request) # to complete life cycle of request.
        return response   
     
    @app.post('/v1/transfers',status_code=201,operation_id='createTransfer',responses={
       401:{'description':'No or Bad token','content': {"application/problem+json": {}}},
       400:{'description':'missing Idempotency-Key','content': {"application/problem+json": {}}},
       404:{'description':'source account not owned by caller (or not existing)','content': {"application/problem+json": {}}},
       409:{'description':'insufficient funds','content': {"application/problem+json": {}}},
       422:{'description':' invalid body, unknown fields, amount over settings.max_transfer_piastres, same source and destination, unknown destination, or key reused with a different body'
            ,'content': {"application/problem+json": {}}},
    }) 
    def create_transfer(body:In_body_transfer,request:Request):
      customer_id=request.state.auth_source_id

      idempotency_key=request.headers.get("Idempotency-Key")
      if idempotency_key is None or len(idempotency_key) == 0:
        raise CustomException(title='missing Idempotency-Key',status=400)

      # check if they are same.
      if body.from_account_id == body.to_account_id:
        raise CustomException(title='same source and destination',status=422)
      
    
      local_session=make_session_factory(app.state.engine)
      with local_session() as session, session.begin():
        Idempotency_record = session.get(IdempotencyRecord, (customer_id, idempotency_key))
          # Operation done ?
        if Idempotency_record is not None: 
            if (Idempotency_record.from_account_id != body.from_account_id
                    or Idempotency_record.to_account_id != body.to_account_id
                    or Idempotency_record.amount_piastres != body.amount_piastres
                    or Idempotency_record.memo != body.memo): # if different body sent with the same key.
                raise CustomException(title="key reused with a different body",
                                     status=422)
            else: # replay the response
               return JSONResponse(content=Idempotency_record.response_body,
                status_code=Idempotency_record.status_code,
                headers={'Idempotent-Replayed':'true'},
                media_type="application/problem+json" if Idempotency_record.status_code//100 ==4 else "application/json"
                )
        else:
        # 0) check if the authenticated one is the sender.
            sender = session.get(Account, body.from_account_id)
            receiver = session.get(Account, body.to_account_id)

            if sender is None or customer_id !=sender.owner_id:
               raise CustomException(title='source account not owned by caller (or not existing)',status=404)
            if receiver is None:
               raise CustomException(title='unknown destination',status=422)
            
        # 1) debit the sender (only if the balance is enough)
            debit = session.execute(
                update(Account)
                .where(Account.id == body.from_account_id, Account.balance_piastres >= body.amount_piastres)
                .values(balance_piastres=Account.balance_piastres - body.amount_piastres)
            )
            if debit.rowcount == 0:
                Idempotency_record=IdempotencyRecord(
                id=customer_id,
                key=idempotency_key,
                from_account_id=body.from_account_id,
                to_account_id=body.to_account_id,
                amount_piastres=body.amount_piastres,
                memo=body.memo,
                status_code=409,
                response_body={"type": "about:blank",'title':"Insufficient funds","status":409}
                )
                session.add(Idempotency_record)
                return JSONResponse(content={"type":"about:blank",
                                    "title":"Insufficient funds","status":409},
                                    status_code=409, media_type="application/problem+json")

            # 2) credit the receiver
            credit = session.execute(
                update(Account)
                .where(Account.id == body.to_account_id)
                .values(balance_piastres=Account.balance_piastres + body.amount_piastres)
            )

            # 3) record the transfer
            transfer = Transfer(
                id=f"trf_{uuid.uuid4().hex[:28]}",
                from_account_id=body.from_account_id,
                to_account_id=body.to_account_id,
                amount_piastres=body.amount_piastres,
                memo=body.memo,
                status="completed",
            )
            session.add(transfer)  
            # covert to dict because FastAPI can not serialize a raw ORM object.
            result = {
            "id": transfer.id,
            "from_account_id": transfer.from_account_id,
            "to_account_id": transfer.to_account_id,
            "amount_piastres": transfer.amount_piastres,
            "memo": transfer.memo,
            "status": transfer.status
            }  

            # 4) adding idempotency record
            Idempotency_record=IdempotencyRecord(
                id=customer_id,
                key=idempotency_key,
                from_account_id=body.from_account_id,
                to_account_id=body.to_account_id,
                amount_piastres=body.amount_piastres,
                memo=body.memo,
                status_code=201,
                response_body=result
            )
            session.add(Idempotency_record)
            #end of seesion     
 
      return result


    @app.get('/v1/accounts/{account_id}',status_code=200,operation_id='getAccount',responses={
       401:{'description':'No or Bad token','content': {"application/problem+json": {}}},
       404:{'description':'source account not owned by caller (or not existing)','content': {"application/problem+json": {}}},
    })
    def get_account(account_id:str,request:Request):
        customer_id=request.state.auth_source_id

        local_session=make_session_factory(app.state.engine)
        with local_session() as session, session.begin():
            account=session.get(Account, account_id)
            if account is None or account.owner_id != customer_id:
               raise CustomException(title='source account not owned by caller (or not existing)',status=404)

            result={
               "id":account.id,
                "balance_piastres":account.balance_piastres,
                "currency":account.currency
            }
        return result


    @app.get('/v1/transfers/{transfer_id}',status_code=200,operation_id='getTransfer',responses={
       401:{'description':'No or Bad token','content': {"application/problem+json": {}}},
       404:{'description':'source or destination account not owned by caller (or not existing)','content': {"application/problem+json": {}}},
    })
    def get_transfer(transfer_id:str,request:Request):
        customer_id=request.state.auth_source_id

        local_session=make_session_factory(app.state.engine)
        with local_session() as session, session.begin():
            transfer=session.get(Transfer, transfer_id)
            if transfer is None :
                raise CustomException(title='source or destination account not owned by caller (or not existing)',status=404)
            # get accounts to compare ids.
            s = session.get(Account, transfer.from_account_id)
            r = session.get(Account, transfer.to_account_id)

            if (s.owner_id!=customer_id and r.owner_id!=customer_id):
                raise CustomException(title='source or destination account not owned by caller (or not existing)',status=404)

            result = {
                "id": transfer.id,
                "from_account_id": transfer.from_account_id,
                "to_account_id": transfer.to_account_id,
                "amount_piastres": transfer.amount_piastres,
                "memo": transfer.memo,
                "status": transfer.status
                }  
        return result
    
    return app
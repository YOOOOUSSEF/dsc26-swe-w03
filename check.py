import time
import uuid
api_tokens:dict[str:dict]={"a":"ew","b":'zw'}
rate_limit_capacity=3
bucket:dict[str,dict[str]]={}  
for item in api_tokens.values():
    bucket[item]={}
    bucket[item]['token']=rate_limit_capacity
    bucket[item]['last_refill']=time.perf_counter()

print(bucket)

# from app.settings import Settings
# settings=Settings()
# start=settings.clock()
# for i in range(1000_000_00):
#     pass
# end=settings.clock()
# print(int(end-start))
integer_time=0
ps={'Retry-After':integer_time if integer_time>=1 else 1}
print(ps)
print(uuid.uuid4().hex)
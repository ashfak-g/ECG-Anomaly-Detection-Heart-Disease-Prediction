                                          Table "public.audit_log"
    Column     |            Type             | Collation | Nullable |                Default                
---------------+-----------------------------+-----------+----------+---------------------------------------
 id            | integer                     |           | not null | nextval('audit_log_id_seq'::regclass)
 user_id       | integer                     |           |          | 
 action        | character varying(100)      |           | not null | 
 resource_type | character varying(50)       |           |          | 
 resource_id   | integer                     |           |          | 
 timestamp     | timestamp without time zone |           |          | now()
 details       | json                        |           |          | 
Indexes:
    "audit_log_pkey" PRIMARY KEY, btree (id)
    "idx_audit_log_timestamp" btree ("timestamp" DESC)
    "idx_audit_log_user_id" btree (user_id)
Foreign-key constraints:
    "audit_log_user_id_fkey" FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE SET NULL

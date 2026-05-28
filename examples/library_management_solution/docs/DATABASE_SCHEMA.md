# Database Schema

```sql
create table books (
  id bigint primary key,
  isbn varchar(32) not null unique,
  title varchar(128) not null,
  author varchar(128),
  category varchar(64),
  total_copies int not null,
  available_copies int not null,
  created_at timestamp not null
);

create table readers (
  id bigint primary key,
  card_no varchar(32) not null unique,
  name varchar(64) not null,
  phone varchar(32),
  borrow_limit int not null default 5,
  status varchar(32) not null
);

create table borrow_orders (
  id bigint primary key,
  book_id bigint not null,
  reader_id bigint not null,
  status varchar(32) not null,
  borrowed_at timestamp not null,
  due_at timestamp not null,
  returned_at timestamp null,
  fine_amount decimal(10,2) not null default 0
);

create table operator_logs (
  id bigint primary key,
  operator_id bigint not null,
  action varchar(64) not null,
  target_type varchar(64) not null,
  target_id bigint not null,
  detail text,
  created_at timestamp not null
);
```

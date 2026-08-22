from sqlmodel import SQLModel


class User(SQLModel, table=True):
    pass


class Pharmacy(SQLModel, table=True):
    pass


class Order(SQLModel, table=True):
    pass

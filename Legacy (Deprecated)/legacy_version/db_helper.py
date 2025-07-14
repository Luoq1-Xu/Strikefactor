# Description: This file is used to connect to the database and update info.
import sqlalchemy as db

URL = "postgresql://default:ty2SPEQ5nYKL@ep-cool-union-a1z2k2jn-pooler.ap-southeast-1.aws.neon.tech:5432/verceldb?sslmode=require"

FIELDS = [
    'name',
    'pitch_count',
    'strikes',
    'balls',
    'strikeouts',
    'walks',
    'outs',
    'hits_allowed',
    'runs_allowed',
    'home_runs_allowed',
]

def get_pitcher_stats(name):
    print("start")
    engine = db.create_engine(URL)
    connection = engine.connect()
    pitchers = db.Table('pitchers', db.MetaData(), autoload_with=engine)
    query = db.select(pitchers).where(pitchers.c.name == name)
    result_proxy = connection.execute(query)
    print('query successful')
    result_set = result_proxy.fetchall()
    connection.close()
    return dict(zip(FIELDS, result_set[0][1:]))

def insert_pitcher(name):
    values_list = [
        {
            'name': name,
            'pitch_count': 0,
            'strikes': 0,
            'balls': 0,
            'strikeouts': 0,
            'walks': 0,
            'outs': 0,
            'hits_allowed': 0,
            'runs_allowed': 0,
            'home_runs_allowed': 0
        }
    ]
    engine = db.create_engine(URL)
    connection = engine.connect()
    pitchers = db.Table('pitchers', db.MetaData(), autoload_with=engine)
    query = db.insert(pitchers) \
        .values(name=name,
                pitch_count=0,
                strikes=0,
                balls=0,
                strikeouts=0,
                walks=0,
                outs=0,
                hits_allowed=0,
                runs_allowed=0,
                home_runs_allowed=0)
    result_proxy = connection.execute(query)
    connection.commit()
    connection.close()

def update_info(name: str, values: dict):
    engine = db.create_engine(URL)
    connection = engine.connect()
    pitcher_stats = get_pitcher_stats(name)
    for key in values:
        pitcher_stats[key] += values[key]
    pitchers = db.Table('pitchers', db.MetaData(), autoload_with=engine)
    query = db.update(pitchers) \
        .where(pitchers.columns.name == name) \
        .values(pitcher_stats)
    result_proxy = connection.execute(query)
    connection.commit()
    connection.close()
    print("done.")

def reset_pitcher_stats(name):
    engine = db.create_engine(URL)
    connection = engine.connect()
    pitchers = db.Table('pitchers', db.MetaData(), autoload_with=engine)
    query = db.update(pitchers) \
        .where(pitchers.columns.name == name) \
        .values({
            'pitch_count': 0,
            'strikes': 0,
            'balls': 0,
            'strikeouts': 0,
            'walks': 0,
            'outs': 0,
            'hits_allowed': 0,
            'runs_allowed': 0,
            'home_runs_allowed': 0
        })
    result_proxy = connection.execute(query)
    connection.commit()
    connection.close()
    print("done.")

# Values for different ratings
NEGATIVE_RATING = -1
NEUTRAL_RATING = 0
POSITIVE_RATING = 1
SKIP_RATING = 12

# The maximum number of mistakes on verification tweets before the worker is banned
MAX_STRIKES = 3

# how often (int HITs) to include a verification tweet in the rating set
VERIFY_INTERVAL = 3

TWEETS_PER_HIT = 5
DESIRED_RATINGS = 3

options.sentiment = {
    'price' : [0.01],
    'mystery_task' : False
    }

db.define_table('tweets',
               db.Field('tweetid', 'bigint'),
               db.Field('name', 'text'),
               db.Field('text', 'text'),
               db.Field('ratings', type='integer', default=0),
               db.Field('skips', type='integer', default=0),
               migrate=migratep, fake_migrate=fake_migratep)

db.define_table('ratings',
               db.Field('study', db.studies),
               db.Field('hitid', 'text'),
               db.Field('workerid', 'text'),
               db.Field('assid', 'text'),
               db.Field('condition', db.conditions),
               db.Field('time', type='datetime', default=now),
               db.Field('worker_rating_count', 'integer'),
               db.Field('duration', 'float'),
               db.Field('ip', 'text'),
               db.Field('tweet', db.tweets),
               db.Field('tweetid', 'bigint'),
               db.Field('rating', 'integer'),
               db.Field('skip', 'boolean', default=False),
               db.Field('isstrike', 'boolean'),
               migrate=migratep, fake_migrate=fake_migratep)

db.define_table('workerstats',
                db.Field('id'),
                db.Field('workerid', 'text'),
                db.Field('ratings', type='integer', default=0),
                db.Field('positives', type='integer', default=0),
                db.Field('neutrals', type='integer', default=0),
                db.Field('negatives', type='integer', default=0),
                db.Field('skips', type='integer', default=0),
                db.Field('strikes', type='integer', default=0),
                db.Field('banned', type='boolean', default=False),
                migrate=migratep, fake_migrate=fake_migratep)
    
##
# Get a tweet that the worker rated a while back
##    
def get_verification_tweet(workerid):
    
    # Must have been rated by this worker
    workerCondition = db.ratings.workerid == workerid
    
    # Must be a non-neutral rating
    extremeCondition = (db.ratings.rating == POSITIVE_RATING) | (db.ratings.rating == NEGATIVE_RATING)
    
    # Join tweets against ratings
    joinCondition = db.tweets.id == db.ratings.tweet

    # Group by tweet
    group = db.tweets.id
    
    where = workerCondition & extremeCondition & joinCondition
    
    # Get N tweets
    ordering = db.ratings.worker_rating_count.max()
    
    query = db(where)
    query = query.select(db.tweets.ALL, db.ratings.worker_rating_count.max(), orderby=ordering, groupby=group)
    
    result = query.first().tweets
    return result.as_dict()

def get_unrated_tweets(workerid, numTweets, desiredRatings):
    print 'resorting to unrated tweets...'
    ordering = db.tweets.ratings
    group = db.tweets.id
    join = db.ratings.on(db.tweets.id == db.ratings.tweet)
    limit = (0,numTweets)
    where = (db.tweets.ratings < desiredRatings)
    having =(db.ratings.id.count() == 0)
    
    query = db(where)
    query = query.select(db.tweets.ALL, orderby=ordering, groupby=group, limitby=limit, left=join, having=having)
    
    return query.as_list()

##
# Get a group of N tweets that the given worker should rate.
##
def get_tweets(workerid, numTweets, desiredRatings):
    tweets = []
    
    hitNumber = hits_done(workerid, request.study)
    if not request.live and ("hits_completed" in request.vars):
        hitNumber = int(request.vars.hits_completed)
    
    # Get the worker info
    workerstats = db(db.workerstats.workerid==workerid).select().first()
    if workerstats == None:
        id = db.workerstats.insert(workerid=workerid)
        workerstats = db(db.workerstats.id==id).select().first()

    # Check if it is time for a verification tweet
    if hitNumber % VERIFY_INTERVAL == VERIFY_INTERVAL - 1:
        vertweet = get_verification_tweet(workerid)
        print 'verifying with',vertweet['id'],vertweet['text']
        tweets.append(vertweet)
    
    # Now get the rest of the tweets
    if not request.live and ("tweets" not in request):
        tweets.extend(get_unrated_tweets(workerid, numTweets, desiredRatings))
    else:
        query = db(db.tweets.id.belongs(request.tweets))
        query = query.select(db.tweets.ALL)
        tweets.extend(query.as_list())

    print 'serving up',[t['id'] for t in tweets]
    return tweets

                
def record_tweet_rating(tweetId, rating):
    study = request.study
    hit = request.hitid
    worker = request.workerid
    ass = request.assid
    ip = request.env.remote_addr
    condition = get_condition(request.condition)
    duration = time.time() - float(request.post_vars.start_time)
    
    print 'recording',rating,'for',tweetId
    
    positiveIncrease = 1 if rating == POSITIVE_RATING else 0
    neutralIncrease = 1 if rating == NEUTRAL_RATING else 0
    negativeIncrease = 1 if rating == NEGATIVE_RATING else 0
    skipIncrease = 1 if rating == SKIP_RATING else 0
    isSkip = False
    if rating == SKIP_RATING:
        isSkip = True
        rating = None
        
    # get the worker and tweet info
    workerstats = db(db.workerstats.workerid==worker).select().first()
    tweet = db(db.tweets.id==tweetId).select().first()
    
    # Check if the tweet was rated before, in which case it is a quality check
    priorRatingsOfTweet = db((db.ratings.tweet==tweetId) & (db.ratings.workerid == worker)).select(db.ratings.rating)
    trueRating = priorRatingsOfTweet.first().rating if len(priorRatingsOfTweet) > 0 else None
    
    # if there is a true rating and it doesn't match, this is a strike
    strikeIncrease = 0
    if (trueRating != None) and (trueRating != rating):
        print 'strike for worker',worker
        strikeIncrease = 1
    
    # if the worker has too many strikes, they are banned
    workerBanned = workerstats.banned
    tweetRatingsIncrease = 1
    if workerstats.strikes + strikeIncrease >= MAX_STRIKES:
        workerBanned = True
        block_worker(worker, "Sentiment ratings were too inconsistent")
        
        # remove all their ratings from the ratings count for this tweet
        tweet.update_record(ratings=db.tweets.ratings - len(priorRatingsOfTweet))
    else:
        # add one to the ratings for this tweet
        tweet.update_record(ratings=db.tweets.ratings + 1)
    
    
    # insert the rating record
    db.ratings.insert(study=study,
                      hitid=hit,
                      workerid=worker,
                      assid=ass,
                      ip=ip,
                      worker_rating_count=workerstats.ratings + 1,
                      condition=condition,
                      duration=duration,
                      tweet=tweetId,
                      tweetid=tweet.tweetid,
                      rating=rating,
                      skip=isSkip,
                      isstrike=strikeIncrease == 1)
    
    # update the worker
    workerstats.update_record(ratings=db.workerstats.ratings + 1,
                            positives=db.workerstats.positives + positiveIncrease,
                            neutrals=db.workerstats.neutrals + neutralIncrease,
                            negatives=db.workerstats.negatives + negativeIncrease,
                            skips=db.workerstats.skips + skipIncrease,
                            strikes=db.workerstats.strikes + strikeIncrease,
                            banned=workerBanned)

def launch_test_sentiment_study(task='sentiment'):
    study_name = 'teststudy %s' % task
    launch_sentiment_study(study_name, " ... test ...", task)

def launch_sentiment_study(name, description, task='sentiment'):
    hit_params = {
        'assignments': DESIRED_RATINGS,
        'title' : 'Rate Tweet Sentiment (BONUS)',
        'description' : 'Rate the sentiment of tweets. Preview to see the task and how much it pays. All payments are in bonus.  You will be paid within minutes of finishing the HIT.',
        'keywords' : 'tweets, sentiment, bonus',
    }
    
    conditions = options[task]
    study = get_or_make_one(db.studies.name == name,
                            db.studies,
                            {'name' : name,
                             'launch_date' : datetime.now(),
                             'description' : description,
                             'task' : task,
                             'hit_params' : sj.dumps(hit_params, sort_keys=True)})
    study.update_record(conditions = sj.dumps(conditions, sort_keys=True))
    
    # get all the tweets that need rating
    ratingsCondition = db.tweets.ratings + db.tweets.skips < DESIRED_RATINGS
    
    query = db(ratingsCondition)
    query = query.select(db.tweets.id)
    tweets = query.as_list()
    
    group = []
    hits_scheduled = 0
    for tweet in tweets:
        if len(group) == TWEETS_PER_HIT:
            schedule_hit(datetime.now(), study.id, task, {'tweets': group})
            hits_scheduled += 1
            group = []
            
        group.append(tweet['id'])
    
    if len(group) > 0:
        schedule_hit(datetime.now(), study.id, task, {'tweets': group})
        hits_scheduled += 1
        
    db.commit()
    print "Scheduled",hits_scheduled,"hits"
    
def reset_sentiment_study():
    db.ratings.truncate('RESTART IDENTITY')
    db.workerstats.truncate('RESTART IDENTITY')
    db(db.tweets).update(ratings=0, skips=0)
    
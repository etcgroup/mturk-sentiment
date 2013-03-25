######################

# coding: utf8

#sql to import tweets: COPY tweets (tweetid,name,text) FROM '/home/mjbrooks/sb47-500-tweets.csv' DELIMITERS ',' HEADER CSV;

import random, hashlib, uuid, datetime, time, math
import gluon.contrib.simplejson

if session.flashType:
    response.flashType = session.flashType
    session.flashType = None

response.title = "Tweet Sentiment"

def index():

    warning = None
    error = None
    if request.post_vars.submit:
        warning = process_ratings(request.post_vars)
    else:
        response.start_time = time.time()

    # find out if we need a warning or block
    level = get_worker_level()
    if level == 'warning':
        error = "Your answers have been inconsistent. Please consider each tweet carefully, or you will be prevented from submitting more of these HITs."
    elif level == 'error':
        error = "Your answers have not been consistent enough. You are not able to submit more of these HITs."
        return dict(error=error, price=None, tweets=[], warning=None)
        
    # Get some tweets to rate
    tweets = get_tweets(request.workerid, TWEETS_PER_HIT, DESIRED_RATINGS)
    # randomize the tweet order
    random.shuffle(tweets)

    bonus = LARGE_HIT_PRICE
    if len(tweets) < LARGE_HIT_THRESHOLD:
        bonus = SMALL_HIT_PRICE
    
    return dict(tweets=tweets, error=error, warning=warning, price=bonus)

def review():
    
    workerIndex = 0
    if request.get_vars.page is not None:
        workerIndex = int(request.get_vars.page) - 1
    
    # find the worker
    allWorkers = db(db.workerstats.workerid != None).select(db.workerstats.ALL, orderby=db.workerstats.id)
    
    if request.post_vars.search is not None:
        searchWorkerId = request.post_vars.search
        for i in range(len(allWorkers)):
            if allWorkers[i].workerid == searchWorkerId:
                redirect('/utility/sentiment/review?page=%s' %(i + 1))
    
    workerStats = None
    if workerIndex >= 0 and workerIndex < len(allWorkers):
        workerStats = allWorkers[workerIndex]
        
    nextWorkerIndex = None
    if workerIndex + 1 < len(allWorkers):
        nextWorkerIndex = workerIndex + 1
    
    prevWorkerIndex = None
    if workerIndex - 1 >= 0 and workerIndex - 1 < len(allWorkers):
        prevWorkerIndex = workerIndex - 1
    
    ratedTweets = None
    if workerStats is not None:
        if request.get_vars.ban is not None:
            banned = int(request.get_vars.ban)
            workerStats.banned = banned == 1
            workerStats.update_record()
            redirect('/utility/sentiment/review?page=%s' %(workerIndex + 1))
            
        query = "SELECT MIN(t.text) AS text, MIN(t.id) AS tid, r1.rating, r1.isverify, r1.isstrike, "+\
                   "STRING_AGG(other.rating::text, ',' ORDER BY other.workerid) AS otherratings, "+\
                   "STRING_AGG(other.workerid, ',' ORDER BY other.workerid) AS otherworkers "+\
            "FROM ratings AS r1 "+\
            "JOIN tweets AS t ON r1.tweet = t.id "+\
            "LEFT JOIN ratings AS other ON r1.tweet = other.tweet "+\
            "LEFT JOIN workerstats AS ws ON other.workerid = ws.workerid "+\
            "WHERE r1.workerid = %s "+\
              "AND other.workerid != %s "+\
              "AND (other.id IS NULL OR (other.rating IS NOT NULL AND ws.banned != 'T')) "+\
            "GROUP BY r1.id "+\
            "ORDER BY r1.worker_rating_count"
            # no null ratings, unless there are no others
            
        placeholders = [workerStats.workerid, workerStats.workerid]
        ratedTweets = db.executesql(query, placeholders=placeholders, as_dict=True)
        ratedTweets = map(Storage, ratedTweets)
        
        def parser(row):
            row.isverify = True if row.isverify == 'T' else (False if row.isverify == 'F' else None)
            row.isstrike = True if row.isstrike == 'T' else (False if row.isstrike == 'F' else None)
            row.otherworkers = row.otherworkers.split(',') if row.otherworkers is not None else []
            row.otherratings = map(int, row.otherratings.split(',')) if row.otherratings is not None else []
            
            # throw out all but first rating for each worker
            workerRatings = dict()
            otherworkers = []
            otherratings = []
            for i in range(len(row.otherworkers)):
                workerid = row.otherworkers[i]
                if workerid not in workerRatings:
                    rating = row.otherratings[i]
                    otherworkers.append(workerid)
                    otherratings.append(rating)
                    workerRatings[workerid] = rating
                    
            row.otherworkers = otherworkers
            row.otherratings = otherratings
            row.workerratings = workerRatings
            
            row.others = Storage()
            row.others[1] = sum([(1 if rating == 1 else 0) for rating in row.otherratings])
            row.others[0] = sum([(1 if rating == 0 else 0) for rating in row.otherratings])
            row.others[-1] = sum([(1 if rating == -1 else 0) for rating in row.otherratings])
            
            return row
        # parse some values
        ratedTweets = map(parser, ratedTweets)
        
    return dict(workerIndex=workerIndex, 
                nextWorkerIndex=nextWorkerIndex, 
                prevWorkerIndex=prevWorkerIndex,
                workerStats=workerStats, 
                workerCount=len(allWorkers),
                ratedTweets=ratedTweets)

def process_ratings(post_vars):

    ratings = {}
    for tweetId in request.post_vars.tweet_ids:
        if tweetId not in request.post_vars:
            return "You must rate the sentiment of all of the tweets."
            
        rating = int(request.post_vars[tweetId])
        if rating not in [NEGATIVE_RATING, NEUTRAL_RATING, POSITIVE_RATING, SKIP_RATING]:
            return "Invalid rating " + str(rating)
        
        ratings[tweetId] = rating
    
    for id,rating in ratings.iteritems():
        verifies = request.post_vars["%s_verifies" % id] == 'True'
        record_tweet_rating(id, rating, verifies)
        
    bonus = LARGE_HIT_PRICE
    if len(ratings) < LARGE_HIT_THRESHOLD:
        bonus = SMALL_HIT_PRICE
        
    hit_finished(bonus_amount=bonus)
    
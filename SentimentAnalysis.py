#!/usr/bin/env python
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Code to score tweets using AFINN and to generate a set of sentiment score for each person mentioned.
#   usage: ./bin/pyspark SentimentAnalysis.py 
#

"""SentimentAnalysis.py"""

import math
import re
import sys

from StringIO import StringIO
from datetime import datetime
from collections import namedtuple
from operator import add, itemgetter

# Note - SparkContext available as sc, HiveContext available as sqlCtx.
from pyspark import SparkContext
from pyspark import HiveContext
from pyspark.streaming import StreamingContext

sc = SparkContext(appName="PythonSentimentAnalysis")
sqlCtx = HiveContext(sc)

# Read in the word-sentiment list and create a static RDD from it
filenameAFINN = "/home/training/TwitterSentimentAnalysis/AFINN/AFINN-111.txt"

# map applies the lambda function (create a tuple of word and sentiment score) to every item of iterable
# within [ ] and returns a list of results. The dictionary is used here to be able to quickly lookup the
# sentiment score based on the key value 
f = open(filenameAFINN, "r")
texto = f.readlines()
afinn = {}
for line in texto:
    l = line.split()
    if len(l) > 2:
        afinn[' '.join(l[:len(l) - 1])] = int(l[-1])
    else:
        afinn[l[0]] = l[-1]
        afinn[l[-1]] = int(l[-1])
f.close()


# Read in the candidate mapping list and create a static dictionary from it
filenameCandidate = "file:///home/training/TwitterSentimentAnalysis/Candidates/Candidate_Mapping.txt"

# map applies the lambda function
candidates = sc.textFile(filenameCandidate).map(lambda x: (x.strip().split(",")[0],x.strip().split(","))) \
                         .flatMapValues(lambda x:x).map(lambda y: (y[1],y[0])).distinct()

# word splitter pattern
pattern_split = re.compile(r"\W+")

tweets = sqlCtx.sql("select id, text, entities.user_mentions.name from incremental_tweets")

sentiments = []
def sentiment(text):
    words = pattern_split.split(text.lower())
    #sentiments = map(lambda word: afinn.get(word, 0), words)
    for word in words:
        if afinn.has_key(word):
            sentiments.append(int(afinn[word])) 
        else:
            sentiments.append(0)
    if sentiments:
        sentiment = float(sum(sentiments))/math.sqrt(len(sentiments))
    else:
        sentiment = 0
    return sentiment

sentimentTuple = tweets.rdd.map(lambda r: [r.id, r.text, r.name]) \
               .map(lambda r: [sentiment(r[1]),r[2]]) \
               .flatMapValues(lambda x: x) \
               .map(lambda y: (y[1],y[0])) \
               .reduceByKey(lambda x, y: x+y) \
               .sortByKey(ascending=True)
for t in sentimentTuple.collect():
    print(t)
scoreDF = sentimentTuple.join(candidates) \
            .map(lambda (x, y): (y[1],y[0])) \
            .reduceByKey(lambda a, b: a + b) \
            .toDF()

scoreRenameDF = scoreDF.withColumnRenamed("_1","Candidate").withColumnRenamed("_2","Score")

sqlCtx.registerDataFrameAsTable(scoreRenameDF, "SCORE_TEMP")

sqlCtx.sql("INSERT OVERWRITE TABLE candidate_score SELECT Candidate, Score FROM SCORE_TEMP")
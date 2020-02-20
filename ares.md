## (WIP) API Reliability Engineering (AREs)

Similar to [Google SREs](https://en.wikipedia.org/wiki/Site_Reliability_Engineering), AREs are focused managing massively scalable APIs.  A big challenge you have when you have microservices at scale is the management of the calling patterns from UI -> BE.  Without an aggregation tier or some form of management layer, this tangle quickly becomes a mess, especially if you handle millions of requests per second.

We will initially follow the same 5 principles of SREs but with the API lense

* Reduce organizational silos
* Accept failure as normal
* Implement gradual changes
* Leverage tooling and automation
* Measure everything

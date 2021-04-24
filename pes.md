# Product Edge Systems (PES)

``` To enable the best Netflix experience by authorizing, integrating, and delivering API orchestration, access management, and critical edge services at scale. ```

Read our [overview](https://www.linkedin.com/pulse/netflixs-edge-systems-delighting-customers-through-bad-fisher-ogden/)

[AIM](https://sites.google.com/netflix.com/aim/home) (Access & Identity Management)    
Playback Systems (viewing history, bookmarks, licensing, encryption etc)   
API Systems   

### Rallying Cry

``` Catalyze Product Evolution ``` (CAPE)

## API Systems

```⌛️ to 🚀 (hourglass to turbine), be the engine for engineering leverage at Netflix```


API Systems encompasses two core areas, the Netflix API and Products’ Edge.  The Netflix API enables signup, content discovery, and partner experiences on 1000+ device types. The team creates a unified abstraction and aggregation layer over disparate Netflix mid-tier systems, enabling device teams to build innovative user experiences through a consistent API layer.  The Products’ Edge focuses on applications behind the scenes that power a variety of our internal workflows.  An example is Studio Edge, an unified GraphQL API that is federated across 60+ backend services and powers our entire content engineering workflow from pitch to play utilized by Netflix employees, vendors, contractors and creative talent.

Org Responsibilities:
* Expose a singular API to client devices to navigate our Netflix experience
* Maintain an end-to-end development workflow for our APIs and providing multiple entry points into our core aggregation layer
* Maintain a massively scalable, resilient API aggregation layer that 

### Netflix API Team

aka: DNA

This team focuses on building the aggregation tier that stitches together hundreds of backend services and libraries into a single unified data model and schema.  This is then materialized in a variety of ways, through REST APIs, our custom Groovy execution engine (.NEXT), Graph based API (DNA API) and soon to be GraphQL.  The team manages a complex dependency pipeline and sophisticated data model, and operates a Tier 1 service at Netflix.

This team is broken up into two sub-teams

#### Experiences
aka: DNA-X

We maintain the API interaction points between UI teams and the API Runtime.  This includes things like DNA.js, DNA Repl, migration to EdgePaaS and its eventual replacement, GraphQL.  We advocate for UI concerns when modeling APIs and interacting with backend services, such as integrations with NAPA, NES, and Hendrix.  We also push UI partners to rethink calling patterns and/or interaction models such as Session Context Service, Feature flagging and separation of the Growth API.

#### Runtime
aka: DNA-R

We provide the critical connective layer between the APIs consumed by our Netflix app and the backend microservices that power our product experiences.  We enable highly aligned, loosely coupled engineering teams by decoupling the UI and mid-tier concerns allowing for independent innovation.  This is done by creating a consistent, uniform, resilient  API engine that provides a composite data model spanning all backend concerns, rich context aggregation, fault tolerance around service and architectural iterations all in an easily accessible and extensible interface.

### Federated API Gateway Team

aka: BFG

This team develops a scalable API platform that accommodates rapid iteration across mid-tier and backend teams while providing a unified, discoverable API to clients.  The current scope includes the GraphQL gateway, schema registry and federation sdk.   Our current focus areas are Studio Edge, the unified GraphQL API for our content/studio applications and Consumer Edge, unifying our MemberUIs (TVUI, Web, iOS, and Android) on a single GraphQL API.  Additionally, our team is a key contributor to advancing GraphQL adoption across Netflix.

## Background

[Cloud Edge Architecture](https://bit.ly/3vlEQQ9)    
[Edge architecture](https://www.youtube.com/watch?v=5ju4W9KAzcY)    
[Edge API Redesign](https://www.infoq.com/presentations/netflix-groovy-scripting/)    
[User Identity](https://www.infoq.com/presentations/netflix-user-identity)    
[Edge Gateway](https://www.infoq.com/presentations/netflix-edge-gateway)    
[Scalability Patterns](https://www.infoq.com/presentations/netflix-edge-scalability-patterns)    

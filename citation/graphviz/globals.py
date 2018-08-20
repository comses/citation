from enum import Enum


class RelationClassifier(Enum):
    """
    Helper class to store the global default name for the visualization Identifier
    """
    JOURNAL = 'Journal'
    SPONSOR = 'Sponsor'
    PLATFORM = 'Platform'
    AUTHOR = 'Author'
    GENERAL = 'General'
    MODELDOCUMENDTATION = 'Modeldoc'


class CodePlatformIdentifier(Enum):
    """
        Helper class to store name of the global defaults for the code archived platform
    """
    COMSES = "COMSES"
    OPEN_SOURCE = "OPEN SOURCE"
    PLATFORM = "PLATFORM"
    JOURNAL = "JOURNAL"
    PERSONAL = "PERSONAL"
    INVALID = "INVALID"
    OTHERS = "OTHERS"


class CacheNames(Enum):
    """
            Helper class to store name of the global defaults use as the key for caching values
    """
    # stores the contribution value for each publication -will need to add pub_id value to fetch for specific publication
    # for e.g cache.get(CacheNames.CONTRIBUTION_DATA.value+str(pub.id))
    CONTRIBUTION_DATA = "citation:contribution_data:pub_id-"
    # stores the distribution information of publication across year with code availablity and non availability information
    DISTRIBUTION_DATA = "citation:distribution_data"
    # stores the count of the identified code_archive_url platform type
    CODE_ARCHIVED_PLATFORM = "citation:code_archived_platform"
    # stores the information about how publication are connected for the default sponsors filter used to cache it
    NETWORK_GRAPH_GROUP_BY_SPONSORS = "citation:network_graph_group_by_sponsors"
    # stores the name of the default sponsors filter used to cache it
    NETWORK_GRAPH_SPONSOS_FILTER = "citation:network_graph_sponsors_filter"
    # stores the information about how publication are connected for the default tags filter used to cache it
    NETWORK_GRAPH_GROUP_BY_TAGS = "citation:network_graph_group_by_tags"
    # stores the name of the default tags filter used to cache it
    NETWORK_GRAPH_TAGS_FILTER = "citation:network_graph_tags_filter"


class NetworkGroupByType(Enum):
    TAGS = 'tags'
    SPONSOR = 'sponsors'

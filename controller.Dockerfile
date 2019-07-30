FROM centos:7
LABEL authors="Antoni Segura Puimedon<toni@kuryr.org>, Michał Dulko<mdulko@redhat.com>"

ARG UPPER_CONSTRAINTS_FILE="https://git.openstack.org/cgit/openstack/requirements/plain/upper-constraints.txt"

RUN yum install -y epel-release \
    && yum install -y --setopt=tsflags=nodocs python-pip \
    && yum install -y --setopt=tsflags=nodocs gcc python-devel git

COPY . /opt/kuryr-kubernetes

RUN pip install -c $UPPER_CONSTRAINTS_FILE --no-cache-dir /opt/kuryr-kubernetes \
    && yum -y history undo last \
    && rm -rf /opt/kuryr-kubernetes \
    && groupadd -r kuryr -g 711 \
    && useradd -u 711 -g kuryr \
         -d /opt/kuryr-kubernetes \
         -s /sbin/nologin \
         -c "Kuryr controller user" \
         kuryr

USER kuryr
CMD ["--config-dir", "/etc/kuryr"]
ENTRYPOINT [ "/usr/bin/kuryr-k8s-controller" ]

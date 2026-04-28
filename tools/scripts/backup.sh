#!/bin/shell

working_path=$(cd "$(dirname "$0")""/../.."; pwd) 
echo working path: $working_path

usage() {
    echo "Usage: sh tools/scripts/backup.sh [options]"
    echo "Options:"
    echo "  -h           Show this help message and exit"
    echo "  -a           Backup full data"
    echo "  -i           Backup important data in mongodb"
    echo "  -s           Backup session.token and device.json"
    exit 1
}


if [ $# -eq 0 ]; then
    usage
fi

output=$working_path"/backups/"`date "+%Y_%m_%d_%H_%M_%S"`
output_latest=$working_path"/backups/latest"

backup_full_mongodb() {
    mongodump -o $output/mongodb
    rm $output_latest/full_mongodb
    ln -s $output/mongodb $output_latest/full_mongodb
    echo "Backup full mongodb data to $output/mongodb"
}

backup_important_data_in_mongodb() {
    mongodump -d PallasBot -c blacklist -o $output/mongodb
    mongodump -d PallasBot -c config -o $output/mongodb
    mongodump -d PallasBot -c group_config -o $output/mongodb
    mongodump -d PallasBot -c user_config -o $output/mongodb
    mongodump -d PallasBot -c context -o $output/mongodb
    # mongodump -d PallasBot -c image_cache -o $output/mongodb

    rm $output_latest/important_data_in_mongodb
    ln -s $output/mongodb $output_latest/important_data_in_mongodb

    echo "Backup important data in mongodb to $output/mongodb"
}

backup_session() {
    for path in `find $working_path/accounts -name "device.json" -or -name "session.token"`; do
        account=`basename $(dirname $path)`
        target=$output/accounts/$account
        mkdir -p $target
        cp $path $target
        
        target_latest=$output_latest/accounts/$account
        mkdir -p $target_latest
        cp $path $target_latest
    done
    
    mkdir -p $output/accounts/binary
    cp $working_path/accounts/binary/accounts.* $output/accounts/binary/

    mkdir -p $output_latest/accounts/binary
    cp $working_path/accounts/binary/accounts.* $output_latest/accounts/binary/

    echo "Backup session.token and device.json to $output/accounts"
}

while getopts "ahis" arg; do
    case $arg in
        a)
            backup_full_mongodb
            backup_session
            ;;
        i)
            backup_important_data_in_mongodb
            ;;
        s)
            backup_session
            ;;
        h)
            usage
            ;;
        ?)
            usage
            ;;
    esac
done
